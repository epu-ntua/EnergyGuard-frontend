
import logging
import os
import requests


logger = logging.getLogger(__name__)


def _fmt_metric_value(value):
    """Format a metric value for display: up to 3 decimal places for floats, pass-through for strings."""
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return str(value)
    return str(value) if value is not None else "—"


def _fmt_metrics_list(metrics):
    return [dict(m, value=_fmt_metric_value(m.get("value"))) for m in metrics]


import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from trustworthiness.jobs import record_job_outcome, release_thread_connection
from trustworthiness.project_access import editable_project, project_picker_redirect, visible_job_assessment


def _robustness_context(context=None):
    base_context = {
        "show_sidebar": True,
        "active_navbar_page": "trustworthiness",
    }
    if context:
        base_context.update(context)
    return base_context


def _robustness_render(request, template_name, context=None, status=None):
    return render(request, template_name, _robustness_context(context), status=status)


def _job_assessment(user, job_id):
    from trustworthiness.models import Assessment
    return visible_job_assessment(user, job_id, Assessment.AssessmentType.ROBUSTNESS)


def _parse_yaml_config(temp_path):
    """Parse the uploaded YAML config file. Returns {} if parsing fails."""
    try:
        import yaml
        with open(temp_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        logger.exception("Failed to parse uploaded YAML config at %s", temp_path)
        return {}


# ---------------------------------------------------------------------------
# Background evaluation job
# ---------------------------------------------------------------------------


def _call_backend_api(config_name, temp_path):
    """POST the YAML to the backend and return the metrics JSON dict.

    Raises RuntimeError when backend/API calls fail.
    """
    api_url = getattr(settings, "ROBUSTNESS_API_URL", "").rstrip("/")
    if not api_url:
        raise RuntimeError("ROBUSTNESS_API_URL is not configured")

    total_timeout = int(getattr(settings, "ROBUSTNESS_API_TIMEOUT", 1800))
    submit_timeout = int(getattr(settings, "ROBUSTNESS_API_SUBMIT_TIMEOUT", 60))
    poll_timeout = int(getattr(settings, "ROBUSTNESS_API_POLL_TIMEOUT", 30))
    poll_interval = float(getattr(settings, "ROBUSTNESS_API_POLL_INTERVAL", 2.0))

    try:
        with open(temp_path, "rb") as f:
            resp = requests.post(
                f"{api_url}/api/evaluations",
                files={"config": (Path(temp_path).name, f, "application/x-yaml")},
                timeout=submit_timeout,
            )
        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"Backend evaluation creation failed ({resp.status_code}): {resp.text}"
            )

        response_payload = resp.json()
        backend_job_id = response_payload.get("job_id")
        if not backend_job_id:
            raise RuntimeError("Backend response did not include a job_id")

        inline_metrics = response_payload.get("metrics")
        if isinstance(inline_metrics, dict) and inline_metrics:
            return inline_metrics, backend_job_id

        status_url = f"{api_url}/api/evaluations/{backend_job_id}"
        metrics_url = f"{api_url}/api/evaluations/{backend_job_id}/metrics"
        deadline = time.time() + max(total_timeout, 1)

        while time.time() < deadline:
            status_resp = requests.get(status_url, timeout=poll_timeout)
            if status_resp.status_code != 200:
                raise RuntimeError(
                    f"Backend status fetch failed ({status_resp.status_code}): {status_resp.text}"
                )

            status_payload = status_resp.json() or {}
            status = status_payload.get("status")
            if status == "failed":
                raise RuntimeError(
                    f"Backend evaluation failed: {status_payload.get('error') or 'unknown error'}"
                )
            if status == "completed":
                break

            time.sleep(max(poll_interval, 0.25))
        else:
            raise RuntimeError(
                f"Backend evaluation timed out after {total_timeout}s while waiting for completion"
            )

        while time.time() < deadline:
            metrics_resp = requests.get(metrics_url, timeout=poll_timeout)
            if metrics_resp.status_code == 200:
                return metrics_resp.json(), backend_job_id
            if metrics_resp.status_code != 404:
                raise RuntimeError(
                    f"Backend metrics fetch failed ({metrics_resp.status_code}): {metrics_resp.text}"
                )
            time.sleep(max(poll_interval, 0.25))

        raise RuntimeError(
            f"Backend metrics not ready after {total_timeout}s for job {backend_job_id}"
        )

    except requests.RequestException as exc:
        raise RuntimeError(f"Backend API request failed: {exc}") from exc


def _run_eval_job(job_id, assessment_id, config_name, temp_path):
    """Runs in a thread; see trustworthiness.jobs."""
    try:
        result, backend_job_id = _call_backend_api(config_name, temp_path)
        # The CSV downloads ask the backend by its own job id
        record_job_outcome(assessment_id, results=result, input_data={"backend_job_id": backend_job_id})
    except Exception as exc:
        logger.exception("Robustness job %s failed", job_id)
        record_job_outcome(assessment_id, error_message=str(exc))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        release_thread_connection()


# ---------------------------------------------------------------------------
# Results context builder
# ---------------------------------------------------------------------------

def _build_results_context(result, config_name, job_id):
    report_generated_at = timezone.localtime().strftime("%Y-%m-%d %H:%M %Z")
    actual_config_name = config_name or result.get("config_name", "Robustness Evaluation")

    metrics = result.get("metrics", {}) or {}
    clean_accuracy = _fmt_pct(result.get("clean_accuracy") or metrics.get("clean_accuracy"))
    robust_accuracy = _fmt_pct(result.get("robust_accuracy") or metrics.get("robust_accuracy"))
    model_name = result.get("model") or result.get("model_name") or metrics.get("model") or "-"
    dataset = result.get("dataset") or metrics.get("dataset") or "-"

    attack_rows = []
    for atk in result.get("attacks", []) or []:
        if not isinstance(atk, dict):
            continue
        attack_rows.append({
            "name": atk.get("name") or atk.get("attack") or "Unknown",
            "epsilon": atk.get("epsilon") or atk.get("eps") or "-",
            "robust_accuracy": _fmt_pct(atk.get("robust_accuracy") or atk.get("accuracy")),
            "success_rate": _fmt_pct(atk.get("success_rate") or atk.get("attack_success_rate")),
            "extra": {
                k: v for k, v in atk.items()
                if k not in {"name", "attack", "epsilon", "eps",
                             "robust_accuracy", "accuracy",
                             "success_rate", "attack_success_rate"}
            },
        })

    report_subtitle = (
        f"Generated on {report_generated_at} from YAML configuration upload. "
        f"Evaluated {len(attack_rows)} attack scenario(s)."
    )

    return {
        "job_id": job_id,
        "config_name": actual_config_name,
        "report_subtitle": report_subtitle,
        "model_name": model_name,
        "dataset": dataset,
        "clean_accuracy": clean_accuracy,
        "robust_accuracy": robust_accuracy,
        "attacks_count": len(attack_rows),
        "attack_rows": attack_rows,
        "metrics": metrics,
        "result": result,
    }


def _fmt_pct(value):
    if value is None:
        return "-"
    try:
        f = float(value)
        return f"{f * 100:.1f}%" if f <= 1.0 else f"{f:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _create_assessment(project, input_data, parent_assessment=None):
    """Assessment id on `project` (already checked with editable_project), or
    None when it could not be saved."""
    try:
        from trustworthiness.models import Assessment
        return Assessment.objects.create(
            project=project,
            assessment_type=Assessment.AssessmentType.ROBUSTNESS,
            input_data=input_data,
            parent_assessment=parent_assessment,
            version=(parent_assessment.version + 1) if parent_assessment else 1,
        ).id
    except Exception:
        logger.exception("Failed to create Assessment for project_id=%s", project.id)
        return None


def _config_to_yaml_text(input_data):
    """Reconstruct a YAML document from the parsed config stored in input_data.

    This is not the original uploaded file byte-for-byte (comments and key
    order are not preserved), only an equivalent re-serialization of the
    parsed config dict already stored on the Assessment.
    """
    import yaml
    config = (input_data or {}).get("config") or {}
    return yaml.dump(config, sort_keys=False, default_flow_style=False)


def _get_owned_assessment(user, assessment_id, for_edit=False):
    """Read access is enough to view an assessment; versioning it (for_edit)
    creates a new one on the project, so it needs write access."""
    from trustworthiness.models import Assessment
    assessment = get_object_or_404(
        Assessment, id=assessment_id, assessment_type=Assessment.AssessmentType.ROBUSTNESS,
    )
    allowed = assessment.project.can_edit(user) if for_edit else assessment.project.is_accessible_by(user)
    if not allowed:
        logger.warning("User %s denied %s access to assessment_id=%s", user.id, "write" if for_edit else "read", assessment_id)
        raise Http404
    return assessment


def _parent_assessment(request, project):
    """The assessment the submitted form edits, when the user may version it
    and it belongs to `project`; else None, and the run is unversioned."""
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


def _edit_context(assessment):
    """The config form editing `assessment`: saving it runs a new version."""
    input_data = assessment.input_data or {}
    original_filename = input_data.get("config_file") or "config.yaml"
    yaml_text = _config_to_yaml_text(input_data)
    return {
        "mode": "edit",
        "parent_assessment_id": assessment.id,
        "project_id": assessment.project_id,
        "config_name": input_data.get("config_name", ""),
        "original_filename": original_filename,
        "ui_state": {"mode": "edit", "original_filename": original_filename, "yaml_text": yaml_text},
    }


@login_required
def config_input_view(request):
    from trustworthiness.models import Assessment

    if request.method == "POST":
        project_id = request.POST.get("project_id", "")
        project = editable_project(request.user, project_id)
        if project is None:
            # No Assessment could record this run: don't start it.
            return project_picker_redirect(request, Assessment.AssessmentType.ROBUSTNESS)

        parent_assessment = _parent_assessment(request, project)
        # An error shows the form again as it was: editing keeps editing.
        form_context = _edit_context(parent_assessment) if parent_assessment else {"project_id": project_id}

        config_file = request.FILES.get("config_file")
        if not config_file:
            return _robustness_render(
                request,
                "robustness/config_input.html",
                {**form_context, "error": "Please select a YAML configuration file before submitting."},
            )

        config_name = request.POST.get("config_name", "").strip() or Path(config_file.name).stem

        suffix = Path(config_file.name).suffix or ".yaml"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in config_file.chunks():
                tmp.write(chunk)

        parsed_config = _parse_yaml_config(tmp.name)
        # Random, not the config's MLflow run id: the job is looked up by this id,
        # and two runs of one config must not share it.
        job_id = uuid.uuid4().hex

        assessment_id = _create_assessment(project, {
            "job_id": job_id,
            "config_name": config_name,
            "config_file": config_file.name,
            "config": parsed_config,
        }, parent_assessment=parent_assessment)
        if assessment_id is None:
            os.unlink(tmp.name)
            return _robustness_render(
                request,
                "robustness/config_input.html",
                {**form_context, "error": "The assessment could not be started. Please try again."},
            )

        threading.Thread(
            target=_run_eval_job,
            args=(job_id, assessment_id, config_name, tmp.name),
            daemon=True,
        ).start()

        return redirect(f"{reverse('robustness:processing')}?job={job_id}")

    project_id = request.GET.get("project_id", "")
    if editable_project(request.user, project_id) is None:
        return project_picker_redirect(request, Assessment.AssessmentType.ROBUSTNESS)
    return _robustness_render(request, "robustness/config_input.html", {
        "project_id": project_id,
    })


@login_required
def processing_view(request):
    job_id = request.GET.get("job")
    if not job_id:
        return redirect("robustness:config_input")

    assessment = _job_assessment(request.user, job_id)
    if assessment is None:
        return _robustness_render(
            request,
            "robustness/processing.html",
            {
                "job_id": job_id,
                "job_status": "failed",
                "analysis_error": "Evaluation job not found. Please submit the configuration again.",
                "config_name": "-",
            },
            status=404,
        )

    config_name = (assessment.input_data or {}).get("config_name", "-")
    project_id = assessment.project_id
    job_status = assessment.status

    if job_status == assessment.Status.COMPLETED:
        return redirect("robustness:results", job_id=job_id)

    if job_status == assessment.Status.FAILED:
        return _robustness_render(
            request,
            "robustness/processing.html",
            {
                "job_id": job_id,
                "job_status": job_status,
                "analysis_error": assessment.error_message or "Unknown evaluation error.",
                "config_name": config_name,
                "project_id": project_id,
            },
            status=502,
        )

    return _robustness_render(
        request,
        "robustness/processing.html",
        {
            "job_id": job_id,
            "job_status": job_status,
            "analysis_error": None,
            "config_name": config_name,
            "project_id": project_id,
            "status_url": reverse("robustness:job_status"),
            "results_base_url": reverse("robustness:results", kwargs={"job_id": "__JOB_ID__"}).replace("__JOB_ID__/", ""),
        },
    )


@login_required
def job_status_api(request):
    job_id = request.GET.get("job")
    if not job_id:
        return JsonResponse({"status": "not_found"}, status=400)
    assessment = _job_assessment(request.user, job_id)
    if assessment is None:
        return JsonResponse({"status": "not_found"}, status=404)
    return JsonResponse({
        "status": assessment.status,
        "error": assessment.error_message,
        "backend_job_id": (assessment.input_data or {}).get("backend_job_id"),
    })


def _report_context_from_result(data):
    attack_profile = data.get("attack_profile", {})
    ap_metrics = attack_profile.get("metrics", [])
    total_queries = next(
        (m.get("value") for m in ap_metrics if m.get("key") == "total_queries_used"),
        None,
    )
    perf_summary = dict(
        data.get("performance_summary", {}),
        primary_metrics=_fmt_metrics_list(data.get("performance_summary", {}).get("primary_metrics", [])),
    )
    attack_profile = dict(attack_profile, metrics=_fmt_metrics_list(ap_metrics))

    return {
        "report_meta": data.get("report_meta", {}),
        "attack_setup": data.get("attack_setup", {}),
        "performance_summary": perf_summary,
        "charts": data.get("charts", {}),
        "attack_profile": attack_profile,
        "total_queries": total_queries,
        "warnings": data.get("warnings", []),
        "highlight_keys": [
            "adversarial_rmse", "adversarial_mse", "rmse_increase", "mse_increase",
            "mae_increase", "accuracy_drop", "attack_success_rate",
        ],
        "report_meta_json": json.dumps(data.get("report_meta", {})),
        "attack_setup_json": json.dumps(data.get("attack_setup", {})),
        "performance_summary_json": json.dumps(data.get("performance_summary", {})),
        "charts_json": json.dumps(data.get("charts", {})),
        "attack_profile_json": json.dumps(attack_profile),
        "warnings_json": json.dumps(data.get("warnings", [])),
    }


@login_required
def results_view(request, job_id):
    """Where the processing page lands when the evaluation completes: the
    results are on the Assessment, so this hands over to its results page."""
    assessment = _job_assessment(request.user, job_id)
    if assessment is None:
        # results_report.html has no place for an error message.
        raise Http404("Job not found.")

    if assessment.status != assessment.Status.COMPLETED:
        return redirect(f"{reverse('robustness:processing')}?job={job_id}")

    return redirect("robustness:view_assessment_results", assessment_id=assessment.id)


@login_required
def view_assessment(request, assessment_id):
    assessment = _get_owned_assessment(request.user, assessment_id)
    input_data = assessment.input_data or {}
    original_filename = input_data.get("config_file", "")
    yaml_text = _config_to_yaml_text(input_data)
    return _robustness_render(request, "robustness/config_input.html", {
        "mode": "view",
        "assessment_id": assessment.id,
        "project_id": assessment.project_id,
        "config_name": input_data.get("config_name", ""),
        "original_filename": original_filename,
        "has_results": assessment.status == assessment.Status.COMPLETED and bool(assessment.results),
        "ui_state": {"mode": "view", "original_filename": original_filename, "yaml_text": yaml_text},
    })


@login_required
def edit_assessment(request, assessment_id):
    assessment = _get_owned_assessment(request.user, assessment_id, for_edit=True)
    return _robustness_render(request, "robustness/config_input.html", _edit_context(assessment))


@login_required
def view_assessment_results(request, assessment_id):
    assessment = _get_owned_assessment(request.user, assessment_id)
    if assessment.status != assessment.Status.COMPLETED or not assessment.results:
        return _robustness_render(request, "robustness/results_report.html", {
            "assessment_id": assessment.id,
            "error": "This assessment has no completed results to display.",
        })

    context = {
        "assessment_id": assessment.id,
        "project_id": assessment.project_id,
        "backend_job_id": (assessment.input_data or {}).get("backend_job_id"),
        "error": None,
        **_report_context_from_result(assessment.results),
    }
    return _robustness_render(request, "robustness/results_report.html", context)


@login_required
def results_json_view(request, job_id):
    assessment = _job_assessment(request.user, job_id)
    if assessment is None:
        return JsonResponse({"error": "Job not found."}, status=404)
    response = JsonResponse(assessment.results or {}, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = f'attachment; filename="robustness-report-{job_id}.json"'
    return response


@login_required
def list_adversarial_csvs_view(request, assessment_id):
    assessment = _get_owned_assessment(request.user, assessment_id)
    backend_job_id = (assessment.input_data or {}).get("backend_job_id")
    if not backend_job_id:
        return JsonResponse({"items": []})

    api_url = getattr(settings, "ROBUSTNESS_API_URL", "").rstrip("/")
    if not api_url:
        return JsonResponse({"items": []})

    try:
        resp = requests.get(
            f"{api_url}/api/evaluations/{backend_job_id}/adversarial-examples",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return JsonResponse({"items": []})

    items = [
        {"attack_key": item["attack_key"], "label": f"Adversarial Examples — {item['attack_key']}"}
        for item in data.get("adversarial_examples", [])
    ]
    return JsonResponse({"items": items})


@login_required
def download_adversarial_csv_view(request, assessment_id, attack_key):
    assessment = _get_owned_assessment(request.user, assessment_id)
    backend_job_id = (assessment.input_data or {}).get("backend_job_id")
    if not backend_job_id:
        return JsonResponse({"error": "No backend job associated with this result."}, status=404)

    api_url = getattr(settings, "ROBUSTNESS_API_URL", "").rstrip("/")
    if not api_url:
        return JsonResponse({"error": "Backend API not configured."}, status=503)

    try:
        resp = requests.get(
            f"{api_url}/api/evaluations/{backend_job_id}/adversarial-examples/{attack_key}",
            timeout=30,
            stream=True,
        )
        if resp.status_code == 404:
            return JsonResponse({"error": "CSV not found for this attack."}, status=404)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return JsonResponse({"error": f"Backend request failed: {exc}"}, status=502)

    from django.http import StreamingHttpResponse
    response = StreamingHttpResponse(
        resp.iter_content(chunk_size=8192),
        content_type="text/csv",
    )
    response["Content-Disposition"] = f'attachment; filename="adversarial_examples_{attack_key}.csv"'
    return response
