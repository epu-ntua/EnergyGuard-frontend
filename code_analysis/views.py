import os
import json
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
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone


SCAN_JOBS = {}
SCAN_JOBS_LOCK = threading.Lock()
REPORTS_DIR = Path(settings.BASE_DIR) / "analysis_reports"
SCAN_API_MAX_RETRIES = max(1, int(os.getenv("SCAN_API_MAX_RETRIES", "3")))
SCAN_API_RETRY_BACKOFF_SEC = max(0.0, float(os.getenv("SCAN_API_RETRY_BACKOFF_SEC", "1.0")))
SCAN_API_RETRY_STATUS_CODES = {502, 503, 504}


def _set_scan_job(job_id, **values):
	with SCAN_JOBS_LOCK:
		job = SCAN_JOBS.setdefault(job_id, {})
		job.update(values)


def _get_scan_job(job_id):
	with SCAN_JOBS_LOCK:
		job = SCAN_JOBS.get(job_id)
		return dict(job) if job else None


def _get_configure_url(source_label):
	routes = {
		"GitHub Repository": "code_analysis:configure_github",
		"Local ZIP File": "code_analysis:configure_upload",
		"JupyterHub Workspace": "code_analysis:configure_jupyter",
	}
	return routes.get(source_label)


def _report_paths(job_id):
	job_dir = REPORTS_DIR / str(job_id)
	return {
		"job_dir": job_dir,
		"report": job_dir / "final_report.json",
		"meta": job_dir / "meta.json",
	}


def _persist_scan_result(job_id, source_label, result):
	paths = _report_paths(job_id)
	paths["job_dir"].mkdir(parents=True, exist_ok=True)
	paths["report"].write_text(json.dumps(result, indent=2), encoding="utf-8")
	paths["meta"].write_text(json.dumps({"job_id": job_id, "source_label": source_label}, indent=2), encoding="utf-8")


def _load_persisted_scan(job_id):
	paths = _report_paths(job_id)
	if not paths["report"].exists():
		return None
	try:
		result = json.loads(paths["report"].read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return None

	source_label = "Stored report"
	if paths["meta"].exists():
		try:
			meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
			if isinstance(meta, dict) and meta.get("source_label"):
				source_label = str(meta.get("source_label"))
		except (OSError, ValueError):
			pass

	return {
		"status": "completed",
		"result": result,
		"source_label": source_label,
		"error": None,
	}


def _add_stepper_context(context, source_label=None, job_id=None):
	context["configure_step_url_name"] = _get_configure_url(source_label) if source_label else None
	context["processing_step_query"] = urlencode({"job": job_id, "source": source_label}) if job_id and source_label else None
	context.setdefault("show_sidebar", True)
	context.setdefault("active_navbar_page", "codeanalysis")
	return context


@login_required
def select_source(request):
	return render(request, "code_analysis/mockup1.html", {
		"show_sidebar": True,
		"active_navbar_page": "codeanalysis",
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


def _run_scan_job(job_id, source_label, mode, payload, upload_meta=None):
	try:
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

		result_payload = response.json()
		_persist_scan_result(job_id, source_label, result_payload)
		_set_scan_job(job_id, status="completed", result=result_payload, error=None)
	except requests.RequestException as exc:
		_set_scan_job(job_id, status="failed", result=None, error=_format_backend_error(exc))
	finally:
		if upload_meta and os.path.exists(upload_meta["temp_path"]):
			os.remove(upload_meta["temp_path"])


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
		"active_navbar_page": "codeanalysis",
	}
	return render(
		request,
		"code_analysis/source_config.html",
		_add_stepper_context(context, source_label="JupyterHub Workspace"),
	)


@login_required
def configure_github(request):
	return render(
		request,
		"code_analysis/configure_github.html",
		_add_stepper_context({
			"show_sidebar": True,
			"active_navbar_page": "codeanalysis",
		}, source_label="GitHub Repository"),
	)


@login_required
def configure_upload(request):
	return render(
		request,
		"code_analysis/configure_upload.html",
		_add_stepper_context({
			"show_sidebar": True,
			"active_navbar_page": "codeanalysis",
		}, source_label="Local ZIP File"),
	)


@login_required
def processing(request):
	source_label = request.POST.get("source_type") or request.GET.get("source") or "Submitted source"
	job_id = request.GET.get("job")
	job_status = None

	if request.method == "POST":
		if source_label == "Local ZIP File" and request.FILES.get("archive_file"):
			upload = request.FILES["archive_file"]
			project_name = _derive_project_name(source_label, request.POST, request.FILES)

			suffix = Path(upload.name).suffix or ".upload"
			with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
				for chunk in upload.chunks():
					tmp_file.write(chunk)
			temp_path = tmp_file.name

			job_id = uuid.uuid4().hex
			_set_scan_job(job_id, status="running", source_label=source_label, result=None, error=None)

			threading.Thread(
				target=_run_scan_job,
				args=(
					job_id,
					source_label,
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
			_set_scan_job(job_id, status="running", source_label=source_label, result=None, error=None)
			threading.Thread(
				target=_run_scan_job,
				args=(job_id, source_label, "github", payload),
				daemon=True,
			).start()
			query = urlencode({"job": job_id, "source": source_label})
			return redirect(f"{request.path}?{query}")

	if job_id:
		job = _get_scan_job(job_id)
		if not job:
			context = _build_processing_context(source_label, analysis_error="Scan job not found. Please submit the analysis again.")
			context["job_id"] = job_id
			context["job_status"] = "failed"
			return render(request, "code_analysis/processing.html", _add_stepper_context(context, source_label=source_label, job_id=job_id), status=404)

		source_label = job.get("source_label") or source_label
		job_status = job.get("status")
		if job_status == "completed":
			return redirect("code_analysis:results", job_id=job_id)
		elif job_status == "failed":
			context = _build_processing_context(source_label, analysis_error=job.get("error") or "Unknown scan error.")
			return render(
				request,
				"code_analysis/processing.html",
				_add_stepper_context({**context, "job_id": job_id, "job_status": job_status}, source_label=source_label, job_id=job_id),
				status=502,
			)
		else:
			context = _build_processing_context(source_label)

		context["job_id"] = job_id
		context["job_status"] = job_status
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
	job = _get_scan_job(job_id)
	if not job:
		return JsonResponse({"status": "not_found"}, status=404)
	return JsonResponse({
		"status": job.get("status"),
		"error": job.get("error"),
	})


@login_required
def results_json(request, job_id):
	job = _get_scan_job(job_id) or _load_persisted_scan(job_id)
	if not job:
		return JsonResponse({"error": "Job not found."}, status=404)
	result = job.get("result") or {}
	response = JsonResponse(result, json_dumps_params={"indent": 2})
	response["Content-Disposition"] = f'attachment; filename="analysis-report-{job_id}.json"'
	return response


@login_required
def results(request, job_id):
	"""Display the raw JSON result of a completed scan job."""
	job = _get_scan_job(job_id) or _load_persisted_scan(job_id)
	if not job:
		return render(request, "code_analysis/results.html", {
			"job_id": job_id,
			"error": "Job not found. The server may have restarted since the scan ran.",
			"result_json": None,
			"show_sidebar": True,
			"active_navbar_page": "codeanalysis",
		})
	if job.get("status") != "completed":
		query = urlencode({"job": job_id, "source": job.get("source_label", "")})
		return redirect(reverse("code_analysis:processing") + f"?{query}")
	source_label = job.get("source_label")
	return render(
		request,
		"code_analysis/results.html",
		_add_stepper_context(
			{
				**_build_results_context(job.get("result") or {}, source_label, job_id),
				"error": None,
				"show_sidebar": True,
				"active_navbar_page": "codeanalysis",
			},
			source_label=source_label,
			job_id=job_id,
		),
	)