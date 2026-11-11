import os
import json
import logging
import re
import time
from pathlib import Path
import tempfile
import threading
import uuid
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from trustworthiness.jobs import record_job_outcome, release_thread_connection
from trustworthiness.project_access import editable_project, project_picker_redirect, visible_job_assessment


logger = logging.getLogger(__name__)

SCAN_API_MAX_RETRIES = max(1, int(os.getenv("SCAN_API_MAX_RETRIES", "3")))
SCAN_API_RETRY_BACKOFF_SEC = max(0.0, float(os.getenv("SCAN_API_RETRY_BACKOFF_SEC", "1.0")))
SCAN_API_RETRY_STATUS_CODES = {502, 503, 504}


def _job_assessment(user, job_id):
	from trustworthiness.models import Assessment
	return visible_job_assessment(user, job_id, Assessment.AssessmentType.CODE_ANALYSIS)


def _get_configure_url(source_label):
	routes = {
		"GitHub Repository": "code_analysis:configure_github",
		"Local ZIP File": "code_analysis:configure_upload",
		"JupyterHub Workspace": "code_analysis:configure_jupyter",
	}
	return routes.get(source_label)


def _add_stepper_context(context, source_label=None, job_id=None):
	context["configure_step_url_name"] = _get_configure_url(source_label) if source_label else None
	context["processing_step_query"] = urlencode({"job": job_id, "source": source_label}) if job_id and source_label else None
	context.setdefault("show_sidebar", True)
	context.setdefault("active_navbar_page", "trustworthiness")
	return context


def _create_assessment(project, input_data, parent_assessment=None):
	"""Assessment id on `project` (already checked with editable_project), or
	None when it could not be saved."""
	try:
		from trustworthiness.models import Assessment
		return Assessment.objects.create(
			project=project,
			assessment_type=Assessment.AssessmentType.CODE_ANALYSIS,
			input_data=input_data,
			parent_assessment=parent_assessment,
			version=(parent_assessment.version + 1) if parent_assessment else 1,
		).id
	except Exception:
		logger.exception("Failed to create Assessment for project_id=%s", project.id)
		return None


def _get_owned_assessment(user, assessment_id, for_edit=False):
	"""Read access is enough to view an assessment; versioning it (for_edit)
	creates a new one on the project, so it needs write access."""
	from trustworthiness.models import Assessment
	assessment = get_object_or_404(
		Assessment, id=assessment_id, assessment_type=Assessment.AssessmentType.CODE_ANALYSIS,
	)
	allowed = assessment.project.can_edit(user) if for_edit else assessment.project.is_accessible_by(user)
	if not allowed:
		logger.warning("User %s denied %s access to assessment_id=%s", user.id, "write" if for_edit else "read", assessment_id)
		raise Http404
	return assessment


def _project_picker_unless_project(request):
	"""The redirect to the hub's project picker when the request names no
	project the user can edit, else None: a scan is never started without a
	project to record its Assessment on."""
	if editable_project(request.user, request.GET.get("project_id")) is not None:
		return None
	from trustworthiness.models import Assessment
	return project_picker_redirect(request, Assessment.AssessmentType.CODE_ANALYSIS)


@login_required
def select_source(request):
	no_project = _project_picker_unless_project(request)
	if no_project:
		return no_project
	return render(request, "code_analysis/mockup1.html", {
		"show_sidebar": True,
		"active_navbar_page": "trustworthiness",
		"project_id": request.GET.get("project_id", ""),
	})


def _derive_project_name(source_label, post_data, files):
	analysis_name = post_data.get("analysis_name", "").strip()
	if analysis_name:
		return analysis_name

	if source_label == "GitHub Repository":
		repo_url = post_data.get("repo_url", "").rstrip("/")
		repo_name = repo_url.split("/")[-1] if repo_url else "github-repository"
		if repo_name.endswith(".git"):
			repo_name = repo_name[:-4]
		return repo_name or "github-repository"

	upload = files.get("archive_file")
	if upload and upload.name:
		filename = Path(upload.name).name
		for suffix in (".tar.gz", ".tgz", ".zip"):
			if filename.lower().endswith(suffix):
				return filename[: -len(suffix)]
		return Path(filename).stem

	return source_label.lower().replace(" ", "-")


def _extract_metric(metrics_payload, metric_key):
	for measure in metrics_payload.get("component", {}).get("measures", []):
		if measure.get("metric") == metric_key:
			return measure.get("value", "0")
	return "0"


def _format_backend_error(exc):
	response = getattr(exc, "response", None)
	if response is not None:
		try:
			payload = response.json()
		except ValueError:
			payload = None
		if isinstance(payload, dict) and payload.get("error"):
			return payload["error"]
		if response.text:
			return response.text
	return str(exc)


def _is_retryable_backend_error(exc):
	if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
		return True

	if isinstance(exc, requests.HTTPError):
		response = getattr(exc, "response", None)
		if response is not None and response.status_code in SCAN_API_RETRY_STATUS_CODES:
			return True

	return False


def _post_with_retry(url, **request_kwargs):
	last_exc = None
	for attempt in range(1, SCAN_API_MAX_RETRIES + 1):
		try:
			response = requests.post(url, **request_kwargs)
			response.raise_for_status()
			return response
		except requests.RequestException as exc:
			last_exc = exc
			if attempt >= SCAN_API_MAX_RETRIES or not _is_retryable_backend_error(exc):
				raise
			time.sleep(SCAN_API_RETRY_BACKOFF_SEC * attempt)

	if last_exc:
		raise last_exc
	raise requests.RequestException("Scan request failed without a specific error.")


def _first_sentence(text):
	clean = " ".join(str(text or "").split())
	if not clean:
		return ""
	match = re.search(r"(.+?[.!?])(?:\s|$)", clean)
	return match.group(1).strip() if match else clean


def _build_processing_context(source_label, analysis_result=None, analysis_error=None):
	issues_payload = analysis_result.get("issues", {}) if analysis_result else {}
	metrics_payload = analysis_result.get("metrics", {}) if analysis_result else {}
	issues_preview = issues_payload.get("issues", [])[:3] if isinstance(issues_payload, dict) else []

	return {
		"source_label": source_label,
		"analysis_result": analysis_result,
		"analysis_error": analysis_error,
		"issues_count": analysis_result.get("issues_found", len(issues_payload.get("issues", []))) if analysis_result else 0,
		"issues_preview": issues_preview,
		"metrics_summary": {
			"bugs": _extract_metric(metrics_payload, "bugs"),
			"vulnerabilities": _extract_metric(metrics_payload, "vulnerabilities"),
			"code_smells": _extract_metric(metrics_payload, "code_smells"),
			"coverage": _extract_metric(metrics_payload, "coverage"),
		},
	}


def _build_results_context(analysis_result, source_label, job_id):
	issues_payload = analysis_result.get("issues", {}) if analysis_result else {}
	legacy_issues = issues_payload.get("issues", []) if isinstance(issues_payload, dict) else []
	taxonomy_payload = analysis_result.get("taxonomy", {}) if analysis_result else {}
	issues_preview = []
	cwe_ids = set(taxonomy_payload.get("cwe", []) if isinstance(taxonomy_payload, dict) else [])
	cve_ids = set(taxonomy_payload.get("cve", []) if isinstance(taxonomy_payload, dict) else [])
	standards_rows = []
	semgrep_incidents = taxonomy_payload.get("incidents", []) if isinstance(taxonomy_payload, dict) else []
	scanned_files = taxonomy_payload.get("scanned_files", []) if isinstance(taxonomy_payload, dict) else []
	semgrep_stats = taxonomy_payload.get("stats", {}) if isinstance(taxonomy_payload, dict) else {}
	taxonomy_by_rule = taxonomy_payload.get("by_rule", {}) if isinstance(taxonomy_payload, dict) else {}
	cwe_desc_by_id = {}
	if isinstance(taxonomy_payload, dict):
		for row in taxonomy_payload.get("standards", []) or []:
			if not isinstance(row, dict):
				continue
			standard_id = str(row.get("standard") or "").upper().strip()
			if not standard_id.startswith("CWE-"):
				continue
			title = str(row.get("title") or "").strip()
			desc = str(row.get("description") or "").strip()
			parts = [part for part in [title, desc] if part]
			if parts and standard_id not in cwe_desc_by_id:
				cwe_desc_by_id[standard_id] = _first_sentence(" - ".join(parts))

	for incident in semgrep_incidents:
		if not isinstance(incident, dict):
			continue
		full_message = str(incident.get("message") or incident.get("rule") or "Unnamed finding")
		issues_preview.append(
			{
				"severity": incident.get("severity") or "INFO",
				"message": full_message,
				"display_message": _first_sentence(full_message),
				"location": incident.get("location") or "Source location not provided",
				"type": incident.get("type") or "SECURITY",
				"rule": incident.get("rule") or "rule unavailable",
				"line": incident.get("line"),
				"status": incident.get("status") or "OPEN",
				"effort": incident.get("effort") or "n/a",
				"cwe_refs": incident.get("cwe_refs") or [],
				"cve_refs": incident.get("cve_refs") or [],
				"metadata_rows": incident.get("metadata_rows") or [],
			}
		)

	# Backward compatibility path for reports that have taxonomy.by_rule but no taxonomy.incidents.
	if not issues_preview and isinstance(taxonomy_by_rule, dict) and taxonomy_by_rule:
		for rule_id, rule_tax in list(taxonomy_by_rule.items()):
			if not isinstance(rule_tax, dict):
				continue
			rule_meta = rule_tax.get("meta", {}) if isinstance(rule_tax.get("meta"), dict) else {}
			metadata_rows = [
				{"key": str(k).replace("_", " ").title(), "value": v}
				for k, v in rule_meta.items()
				if v not in (None, "", [], {})
			]
			metadata_rows.sort(key=lambda item: item["key"])
			issues_preview.append(
				{
					"severity": "INFO",
					"message": rule_meta.get("short_description") or f"Semgrep finding: {rule_id}",
					"display_message": _first_sentence(rule_meta.get("short_description") or f"Semgrep finding: {rule_id}"),
					"location": "Semgrep metadata",
					"type": str(rule_meta.get("category") or "SECURITY").upper(),
					"rule": rule_id,
					"line": None,
					"status": "OPEN",
					"effort": "n/a",
					"cwe_refs": sorted(rule_tax.get("cwe", []) if isinstance(rule_tax.get("cwe"), list) else []),
					"cve_refs": sorted(rule_tax.get("cve", []) if isinstance(rule_tax.get("cve"), list) else []),
					"metadata_rows": metadata_rows,
				}
			)

	# Backward compatibility for reports generated before taxonomy.incidents/stats existed.
	if not issues_preview and legacy_issues:
		for issue in legacy_issues:
			if not isinstance(issue, dict):
				continue
			blob = " ".join(
				[
					str(issue.get("message") or ""),
					str(issue.get("rule") or ""),
					" ".join(str(tag) for tag in (issue.get("tags") or [])),
				]
			)
			issue_cwe_refs = sorted({f"CWE-{m}" for m in re.findall(r"CWE[-:_ ]?(\d+)", blob, flags=re.IGNORECASE)})
			issue_cve_refs = sorted({m.upper() for m in re.findall(r"CVE-\d{4}-\d+", blob, flags=re.IGNORECASE)})

			rule_id = str(issue.get("rule") or "").strip()
			metadata_rows = []
			if rule_id:
				rule_candidates = [rule_id]
				if ":" in rule_id:
					rule_candidates.append(rule_id.split(":", 1)[1])
				for candidate in rule_candidates:
					rule_tax = taxonomy_by_rule.get(candidate)
					if not isinstance(rule_tax, dict):
						continue
					meta = rule_tax.get("meta", {})
					if isinstance(meta, dict) and meta:
						metadata_rows = [
							{"key": str(k).replace("_", " ").title(), "value": v}
							for k, v in meta.items()
							if v not in (None, "", [], {})
						]
						metadata_rows.sort(key=lambda item: item["key"])
						break
			issues_preview.append(
				{
					"severity": issue.get("severity") or "INFO",
					"message": issue.get("message") or issue.get("rule") or "Unnamed finding",
					"display_message": _first_sentence(issue.get("message") or issue.get("rule") or "Unnamed finding"),
					"location": issue.get("component") or issue.get("path") or "Source location not provided",
					"type": issue.get("type") or "SECURITY",
					"rule": issue.get("rule") or "rule unavailable",
					"line": issue.get("line"),
					"status": issue.get("status") or "OPEN",
					"effort": issue.get("effort") or "n/a",
					"cwe_refs": issue_cwe_refs,
					"cve_refs": issue_cve_refs,
					"metadata_rows": metadata_rows,
				}
			)

	if isinstance(taxonomy_payload, dict):
		for row in taxonomy_payload.get("standards", []) or []:
			if not isinstance(row, dict):
				continue
			severity = (row.get("severity") or "INFO").upper()
			if severity not in {"HIGH", "MEDIUM", "LOW", "INFO"}:
				severity = "INFO"
			standards_rows.append(
				{
					"standard": row.get("standard") or "N/A",
					"title": row.get("title") or "Security finding",
					"description": row.get("description") or "",
					"severity": severity,
				}
			)

	if not standards_rows:
		for standard in sorted(cwe_ids):
			standards_rows.append(
				{
					"standard": standard,
					"title": "Detected weakness",
					"description": "Mapped from issue tags or messages.",
					"severity": "MEDIUM",
				}
			)
		for standard in sorted(cve_ids):
			standards_rows.append(
				{
					"standard": standard,
					"title": "Detected vulnerability identifier",
					"description": "Mapped from issue tags or references.",
					"severity": "HIGH",
				}
			)

	# Ensure metadata table always includes explicit CWE and CWE description rows when available.
	for issue in issues_preview:
		if not isinstance(issue, dict):
			continue
		rows = issue.get("metadata_rows") or []
		if not isinstance(rows, list):
			rows = []
		row_keys = {str(item.get("key") or "").strip().lower() for item in rows if isinstance(item, dict)}
		issue_cwe_refs = [str(c).upper().strip() for c in (issue.get("cwe_refs") or []) if str(c).strip()]
		if issue_cwe_refs and "cwe" not in row_keys:
			rows.append({"key": "CWE", "value": ", ".join(sorted(set(issue_cwe_refs)))})
		if issue_cwe_refs and "cwe description" not in row_keys:
			descs = [cwe_desc_by_id.get(cwe) for cwe in sorted(set(issue_cwe_refs)) if cwe_desc_by_id.get(cwe)]
			if descs:
				rows.append({"key": "CWE Description", "value": " | ".join(_first_sentence(d) for d in descs if d)})
		for item in rows:
			if not isinstance(item, dict):
				continue
			key_name = str(item.get("key") or "").strip().lower()
			item["display_value"] = item.get("value")
			# Keep the original value intact for persisted JSON consumers,
			# but shorten description-like metadata in the UI for readability.
			if key_name == "cwe description" or "description" in key_name:
				item["display_value"] = _first_sentence(item.get("value"))
		rows.sort(key=lambda item: str(item.get("key") or ""))
		issue["metadata_rows"] = rows

	top_cwe_counts = {}
	hotspot_files = {}
	overview_source_items = issues_preview
	allowed_files = {
		str(path).strip()
		for path in scanned_files
		if str(path).strip()
	}

	for issue in issues_preview:
		if not isinstance(issue, dict):
			continue
		for cwe in issue.get("cwe_refs") or []:
			cwe_id = str(cwe).upper().strip()
			if not cwe_id:
				continue
			entry = top_cwe_counts.setdefault(cwe_id, {"count": 0, "description": cwe_desc_by_id.get(cwe_id, "")})
			entry["count"] += 1
			if not entry.get("description") and cwe_desc_by_id.get(cwe_id):
				entry["description"] = cwe_desc_by_id[cwe_id]


	for issue in overview_source_items:
		if not isinstance(issue, dict):
			continue
		location = str(issue.get("location") or "Unknown file")
		file_label = location.split(" (line ", 1)[0]
		if ":" in file_label and not file_label.startswith(("./", "/")):
			file_label = file_label.split(":", 1)[1]
		# Restrict hotspots to files known to be scanned in the current run.
		if allowed_files and file_label not in allowed_files:
			continue
		severity_name = str(issue.get("severity") or "INFO").upper()
		bucket = hotspot_files.setdefault(file_label, {"file": file_label, "errors": 0, "warnings": 0, "info": 0, "total": 0})
		if severity_name in {"ERROR", "CRITICAL", "HIGH"}:
			bucket["errors"] += 1
		elif severity_name in {"WARNING", "MEDIUM", "MAJOR"}:
			bucket["warnings"] += 1
		else:
			bucket["info"] += 1
		bucket["total"] += 1

	top_cwe_rows = [
		{
			"id": cwe_id,
			"count": values["count"],
			"description": _first_sentence(values.get("description") or "No Semgrep description available."),
		}
		for cwe_id, values in sorted(top_cwe_counts.items(), key=lambda item: (-item[1]["count"], item[0]))[:5]
	]

	def _hotspot_priority(row):
		# Explicit ordering: files with errors first, then warning-only, then info-only.
		if row["errors"] > 0:
			bucket = 0
		elif row["warnings"] > 0:
			bucket = 1
		else:
			bucket = 2
		return (bucket, -row["errors"], -row["warnings"], -row["total"], row["file"])

	hotspots_preview = []
	for item in sorted(hotspot_files.values(), key=_hotspot_priority)[:6]:
		total = max(item["total"], 1)
		hotspots_preview.append(
			{
				**item,
				"error_width": round((item["errors"] / total) * 100, 2),
				"warning_width": round((item["warnings"] / total) * 100, 2),
				"info_width": round((item["info"] / total) * 100, 2),
			}
		)

	error_total = sum(1 for i in overview_source_items if (i.get("severity") or "").upper() in {"ERROR", "CRITICAL", "HIGH"})
	warning_total = sum(1 for i in overview_source_items if (i.get("severity") or "").upper() in {"WARNING", "MEDIUM", "MAJOR"})
	info_total = sum(1 for i in overview_source_items if (i.get("severity") or "").upper() in {"INFO", "LOW", "MINOR"})
	chart_total = error_total + warning_total + info_total
	fallback_findings_total = len(legacy_issues) if legacy_issues else len(issues_preview)
	findings_total = semgrep_stats.get("findings_total", fallback_findings_total)
	files_scanned_total = semgrep_stats.get("files_scanned", 0)
	if chart_total:
		error_end = round((error_total / chart_total) * 360, 2)
		warning_end = round(error_end + ((warning_total / chart_total) * 360), 2)
		pie_chart_style = (
			"background: conic-gradient("
			f"#d94841 0deg {error_end}deg, "
			f"#f2a93b {error_end}deg {warning_end}deg, "
			f"#4ea6ff {warning_end}deg 360deg"
			")"
		)
	else:
		pie_chart_style = "background: conic-gradient(#dce5f2 0deg 360deg)"

	report_generated_at = timezone.localtime().strftime("%Y-%m-%d %H:%M %Z")
	if source_label == "GitHub Repository":
		report_subtitle = (
			f"Generated on {report_generated_at} from a GitHub repository scan. "
			f"Analyzed {files_scanned_total} files and found {findings_total} findings "
			f"across {len(cwe_ids)} unique CWE IDs."
		)
	elif source_label == "Local ZIP File":
		report_subtitle = (
			f"Generated on {report_generated_at} from uploaded ZIP source code. "
			f"Analyzed {files_scanned_total} files and found {findings_total} findings "
			f"across {len(cwe_ids)} unique CWE IDs."
		)
	else:
		report_subtitle = (
			f"Generated on {report_generated_at} from {source_label}. "
			f"Analyzed {files_scanned_total} files and found {findings_total} findings "
			f"across {len(cwe_ids)} unique CWE IDs."
		)

	return {
		"job_id": job_id,
		"source_label": source_label,
		"analysis_result": analysis_result,
		"project_name": analysis_result.get("project_name", "Analysis Report"),
		"project_key": analysis_result.get("project_key", "-"),
		"report_subtitle": report_subtitle,
		"issues_count": findings_total,
		"semgrep_stats": {
			"files_scanned": files_scanned_total,
			"findings_total": findings_total,
			"scan_time_sec": semgrep_stats.get("scan_time_sec", 0.0),
			"cwe_total": len(cwe_ids),
			"cve_total": len(cve_ids),
		},
		"metrics_summary": {
			"bugs": "-",
			"vulnerabilities": "-",
			"code_smells": "-",
			"coverage": "-",
		},
		"severity_counts": {},
		"severity_buckets": {
			"errors": error_total,
			"warnings": warning_total,
			"info": info_total,
			"total": chart_total,
		},
		"severity_pie_style": pie_chart_style,
		"issues_preview": issues_preview,
		"cwe_items": sorted(cwe_ids)[:8],
		"cve_items": sorted(cve_ids)[:8],
		"standards_rows": standards_rows[:12],
		"top_cwe_rows": top_cwe_rows,
		"hotspots_count": len(hotspots_preview),
		"hotspots_preview": hotspots_preview,
		"quality_summary": {
			"coverage_state": "n/a",
			"risk_state": "n/a",
		},
	}


def _run_scan_job(job_id, assessment_id, mode, payload, upload_meta=None):
	"""Runs in a thread; see trustworthiness.jobs."""
	try:
		if not getattr(settings, "SCAN_API_URL", ""):
			record_job_outcome(assessment_id, error_message="SCAN_API_URL is not configured")
			return
		if mode == "upload":
			temp_path = upload_meta["temp_path"]
			filename = upload_meta["filename"]
			content_type = upload_meta["content_type"]
			with open(temp_path, "rb") as upload_fp:
				response = _post_with_retry(
					f"{settings.SCAN_API_URL}/scan_with_semgrep",
					data=payload,
					files={
						"file": (
							filename,
							upload_fp,
							content_type,
						),
					},
					timeout=settings.SCAN_API_TIMEOUT,
				)
		else:
			response = _post_with_retry(
				f"{settings.SCAN_API_URL}/scan_github_with_semgrep",
				data=payload,
				timeout=settings.SCAN_API_TIMEOUT,
			)

		record_job_outcome(assessment_id, results=response.json())
	except Exception as exc:
		logger.exception("Scan job %s failed", job_id)
		record_job_outcome(assessment_id, error_message=_format_backend_error(exc))
	finally:
		if upload_meta and os.path.exists(upload_meta["temp_path"]):
			os.remove(upload_meta["temp_path"])
		release_thread_connection()


@login_required
def configure_jupyter(request):
	context = {
		"page_title": "Configure JupyterHub Workspace",
		"page_subtitle": "Select a project and folder to analyze code from your JupyterHub environment.",
		"primary_label": "Select Project",
		"primary_placeholder": "Energy Community Simulation",
		"secondary_label": "Select Folder",
		"secondary_placeholder": "data/experiments/simulation_1/",
		"submit_label": "Submit",
		"source_type": "JupyterHub Workspace",
		"show_sidebar": True,
		"active_navbar_page": "trustworthiness",
	}
	return render(
		request,
		"code_analysis/source_config.html",
		_add_stepper_context(context, source_label="JupyterHub Workspace"),
	)


@login_required
def configure_github(request):
	no_project = _project_picker_unless_project(request)
	if no_project:
		return no_project
	return render(
		request,
		"code_analysis/configure_github.html",
		_add_stepper_context({
			"show_sidebar": True,
			"active_navbar_page": "trustworthiness",
			"project_id": request.GET.get("project_id", ""),
		}, source_label="GitHub Repository"),
	)


@login_required
def configure_upload(request):
	no_project = _project_picker_unless_project(request)
	if no_project:
		return no_project
	return render(
		request,
		"code_analysis/configure_upload.html",
		_add_stepper_context({
			"show_sidebar": True,
			"active_navbar_page": "trustworthiness",
			"project_id": request.GET.get("project_id", ""),
		}, source_label="Local ZIP File"),
	)


def _assessment_not_started(request, source_label, project_id):
	"""The processing page in its failed state, for a scan whose Assessment
	could not be saved and which therefore never started."""
	context = _build_processing_context(source_label, analysis_error="The analysis could not be started. Please try again.")
	context.update(job_status="failed", project_id=project_id)
	return render(request, "code_analysis/processing.html", _add_stepper_context(context, source_label=source_label), status=500)


def _parent_assessment(request, project):
	"""The assessment the submitted form edits, when the user may version it
	and it belongs to `project`; else None, and the scan is unversioned."""
	parent_assessment_id = request.POST.get("parent_assessment_id", "").strip()
	if not parent_assessment_id:
		return None
	try:
		parent = _get_owned_assessment(request.user, int(parent_assessment_id), for_edit=True)
	except (ValueError, Http404):
		parent = None
	if parent is None or parent.project_id != project.id:
		logger.warning(
			"Invalid or inaccessible parent_assessment_id=%s for user %s; creating an unversioned assessment instead",
			parent_assessment_id, request.user.id,
		)
		return None
	return parent


@login_required
def processing(request):
	source_label = request.POST.get("source_type") or request.GET.get("source") or "Submitted source"
	job_id = request.GET.get("job")
	job_status = None

	if request.method == "POST":
		from trustworthiness.models import Assessment

		project_id = request.POST.get("project_id", "")
		project = editable_project(request.user, project_id)
		if project is None:
			# No Assessment could record this scan: don't start it.
			return project_picker_redirect(request, Assessment.AssessmentType.CODE_ANALYSIS)

		parent_assessment = _parent_assessment(request, project)

		if source_label == "Local ZIP File" and request.FILES.get("archive_file"):
			upload = request.FILES["archive_file"]
			project_name = _derive_project_name(source_label, request.POST, request.FILES)

			job_id = uuid.uuid4().hex
			assessment_id = _create_assessment(project, {
				"source": source_label,
				"job_id": job_id,
				"analysis_name": project_name,
				"root_folder": request.POST.get("root_folder", "").strip(),
				"archive_filename": upload.name,
			}, parent_assessment=parent_assessment)
			if assessment_id is None:
				return _assessment_not_started(request, source_label, project_id)

			suffix = Path(upload.name).suffix or ".upload"
			with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
				for chunk in upload.chunks():
					tmp_file.write(chunk)
			temp_path = tmp_file.name

			threading.Thread(
				target=_run_scan_job,
				args=(
					job_id,
					assessment_id,
					"upload",
					{"project_name": project_name},
					{
						"temp_path": temp_path,
						"filename": upload.name,
						"content_type": upload.content_type or "application/octet-stream",
					},
				),
				daemon=True,
			).start()

			query = urlencode({"job": job_id, "source": source_label})
			return redirect(f"{request.path}?{query}")

		if source_label == "GitHub Repository" and request.POST.get("repo_url"):
			project_name = _derive_project_name(source_label, request.POST, request.FILES)
			payload = {
				"repo_url": request.POST.get("repo_url", "").strip(),
				"project_name": project_name,
				"branch": request.POST.get("branch", "").strip(),
				"subdirectory": request.POST.get("subdirectory", "").strip(),
				"access_token": request.POST.get("pat", "").strip(),
			}
			payload = {key: value for key, value in payload.items() if value}

			job_id = uuid.uuid4().hex
			assessment_id = _create_assessment(project, {
				"source": source_label,
				"job_id": job_id,
				"repo_url": request.POST.get("repo_url", "").strip(),
				"branch": request.POST.get("branch", "").strip(),
				"subdirectory": request.POST.get("subdirectory", "").strip(),
			}, parent_assessment=parent_assessment)
			if assessment_id is None:
				return _assessment_not_started(request, source_label, project_id)
			threading.Thread(
				target=_run_scan_job,
				args=(job_id, assessment_id, "github", payload),
				daemon=True,
			).start()
			query = urlencode({"job": job_id, "source": source_label})
			return redirect(f"{request.path}?{query}")

	if job_id:
		assessment = _job_assessment(request.user, job_id)
		if assessment is None:
			context = _build_processing_context(source_label, analysis_error="Scan job not found. Please submit the analysis again.")
			context["job_id"] = job_id
			context["job_status"] = "failed"
			return render(request, "code_analysis/processing.html", _add_stepper_context(context, source_label=source_label, job_id=job_id), status=404)

		source_label = (assessment.input_data or {}).get("source") or source_label
		project_id = assessment.project_id
		job_status = assessment.status
		if job_status == assessment.Status.COMPLETED:
			return redirect("code_analysis:results", job_id=job_id)
		elif job_status == assessment.Status.FAILED:
			context = _build_processing_context(source_label, analysis_error=assessment.error_message or "Unknown scan error.")
			return render(
				request,
				"code_analysis/processing.html",
				_add_stepper_context({**context, "job_id": job_id, "job_status": job_status, "project_id": project_id}, source_label=source_label, job_id=job_id),
				status=502,
			)
		else:
			context = _build_processing_context(source_label)

		context["job_id"] = job_id
		context["job_status"] = job_status
		context["project_id"] = project_id
		return render(request, "code_analysis/processing.html", _add_stepper_context(context, source_label=source_label, job_id=job_id))

	context = _build_processing_context(source_label)
	context["job_id"] = job_id
	context["job_status"] = job_status
	return render(request, "code_analysis/processing.html", _add_stepper_context(context, source_label=source_label, job_id=job_id))


@login_required
def job_status_api(request):
	"""Return the current status of a background scan job as JSON."""
	job_id = request.GET.get("job")
	if not job_id:
		return JsonResponse({"status": "not_found"}, status=400)
	assessment = _job_assessment(request.user, job_id)
	if assessment is None:
		return JsonResponse({"status": "not_found"}, status=404)
	return JsonResponse({
		"status": assessment.status,
		"error": assessment.error_message,
	})


@login_required
def results(request, job_id):
	"""Where the processing page lands when the scan completes: the results
	are on the Assessment, so this hands over to its results page."""
	assessment = _job_assessment(request.user, job_id)
	if assessment is None:
		return render(request, "code_analysis/results.html", {
			"job_id": job_id,
			"error": "Job not found. Open the scan's results from the project's assessments.",
			"result_json": None,
			"show_sidebar": True,
			"active_navbar_page": "trustworthiness",
		})
	if assessment.status != assessment.Status.COMPLETED:
		query = urlencode({"job": job_id, "source": (assessment.input_data or {}).get("source", "")})
		return redirect(reverse("code_analysis:processing") + f"?{query}")
	return redirect("code_analysis:view_assessment_results", assessment_id=assessment.id)


def _template_for_source(source_label):
	return "code_analysis/configure_upload.html" if source_label == "Local ZIP File" else "code_analysis/configure_github.html"


@login_required
def view_assessment(request, assessment_id):
	assessment = _get_owned_assessment(request.user, assessment_id)
	input_data = assessment.input_data or {}
	source_label = input_data.get("source", "")
	context = _add_stepper_context({
		"mode": "view",
		"assessment_id": assessment.id,
		"project_id": assessment.project_id,
		"has_results": assessment.status == assessment.Status.COMPLETED and bool(assessment.results),
		"repo_url": input_data.get("repo_url", ""),
		"branch": input_data.get("branch", ""),
		"subdirectory": input_data.get("subdirectory", ""),
		"analysis_name": input_data.get("analysis_name", ""),
		"root_folder": input_data.get("root_folder", ""),
		"archive_filename": input_data.get("archive_filename", ""),
	}, source_label=source_label)
	return render(request, _template_for_source(source_label), context)


@login_required
def edit_assessment(request, assessment_id):
	assessment = _get_owned_assessment(request.user, assessment_id, for_edit=True)
	input_data = assessment.input_data or {}
	source_label = input_data.get("source", "")
	context = _add_stepper_context({
		"mode": "edit",
		"parent_assessment_id": assessment.id,
		"project_id": assessment.project_id,
		"repo_url": input_data.get("repo_url", ""),
		"branch": input_data.get("branch", ""),
		"subdirectory": input_data.get("subdirectory", ""),
		"analysis_name": input_data.get("analysis_name", ""),
		"root_folder": input_data.get("root_folder", ""),
		"archive_filename": input_data.get("archive_filename", ""),
	}, source_label=source_label)
	return render(request, _template_for_source(source_label), context)


@login_required
def view_assessment_results(request, assessment_id):
	assessment = _get_owned_assessment(request.user, assessment_id)
	if assessment.status != assessment.Status.COMPLETED or not assessment.results:
		return render(request, "code_analysis/results.html", {
			"assessment_id": assessment.id,
			"error": "This assessment has no completed results to display.",
			"result_json": None,
			"show_sidebar": True,
			"active_navbar_page": "trustworthiness",
		})
	input_data = assessment.input_data or {}
	source_label = input_data.get("source", "")
	return render(
		request,
		"code_analysis/results.html",
		_add_stepper_context(
			{
				**_build_results_context(assessment.results, source_label, input_data.get("job_id")),
				"assessment_id": assessment.id,
				"project_id": assessment.project_id,
				"error": None,
				"show_sidebar": True,
				"active_navbar_page": "trustworthiness",
			},
			source_label=source_label,
		),
	)


@login_required
def assessment_results_json(request, assessment_id):
	assessment = _get_owned_assessment(request.user, assessment_id)
	if assessment.status != assessment.Status.COMPLETED or not assessment.results:
		return JsonResponse({"error": "This assessment has no completed results."}, status=404)
	response = JsonResponse(assessment.results, json_dumps_params={"indent": 2})
	response["Content-Disposition"] = f'attachment; filename="analysis-report-{assessment.id}.json"'
	return response
