
# --- Report from JSON or API ---
import logging
import os
import requests
from django.views.decorators.csrf import csrf_exempt


logger = logging.getLogger(__name__)


def fetch_metrics_json():
    # Prefer an explicit report path, then the latest persisted run, then a demo fallback.
    from pathlib import Path

    from django.conf import settings

    candidates = []

    env_path = os.getenv("ROBUSTNESS_REPORT_JSON")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    reports_dir = Path(getattr(settings, "REPORTS_DIR", ""))
    if reports_dir.exists():
        for filename in ("final_report.json", "metrics.json"):
            matches = sorted(
                reports_dir.rglob(filename),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            candidates.extend(matches)

    candidates.append(
        Path(__file__).resolve().parents[2]
        / "outputs/mlflow/blackbox_pytorch_regression/metrics.json"
    )

    for json_path in candidates:
        if not json_path.exists():
            continue
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    raise FileNotFoundError(
        "No robustness metrics JSON could be found. Set ROBUSTNESS_REPORT_JSON or run an evaluation first."
    )

def _fmt_metric_value(value):
    """Format a metric value for display: up to 3 decimal places for floats, pass-through for strings."""
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return str(value)
    return str(value) if value is not None else "—"


def _fmt_metrics_list(metrics):
    return [dict(m, value=_fmt_metric_value(m.get("value"))) for m in metrics]


@csrf_exempt
def report_from_json_view(request):
    data = fetch_metrics_json()
    import json
    attack_profile = data.get("attack_profile", {})
    total_queries = None
    ap_metrics = attack_profile.get("metrics", [])
    for m in ap_metrics:
        if m.get("key") == "total_queries_used":
            total_queries = m.get("value")
            break

    perf_summary = data.get("performance_summary", {})
    perf_summary = dict(perf_summary, primary_metrics=_fmt_metrics_list(
        perf_summary.get("primary_metrics", [])
    ))
    attack_profile = dict(attack_profile, metrics=_fmt_metrics_list(ap_metrics))

    context = {
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
        # Add JSON-serialized versions for JS
        "report_meta_json": json.dumps(data.get("report_meta", {})),
        "attack_setup_json": json.dumps(data.get("attack_setup", {})),
        "performance_summary_json": json.dumps(data.get("performance_summary", {})),
        "charts_json": json.dumps(data.get("charts", {})),
        "attack_profile_json": json.dumps(attack_profile),
        "warnings_json": json.dumps(data.get("warnings", [])),
    }
    return _robustness_render(request, "robustness/results_report.html", context)
import json
import os
import re
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


# ---------------------------------------------------------------------------
# In-memory job store (thread-safe)
# ---------------------------------------------------------------------------

EVAL_JOBS = {}
EVAL_JOBS_LOCK = threading.Lock()
REPORTS_DIR = Path(settings.REPORTS_DIR)


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


def _set_job(job_id, **values):
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.setdefault(job_id, {})
        job.update(values)


def _get_job(job_id):
    with EVAL_JOBS_LOCK:
        job = EVAL_JOBS.get(job_id)
        return dict(job) if job else None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _report_paths(job_id):
    job_dir = REPORTS_DIR / str(job_id)
    return {
        "job_dir": job_dir,
        "report": job_dir / "final_report.json",
        "meta": job_dir / "meta.json",
    }


def _persist_result(job_id, config_name, result, backend_job_id=None, assessment_id=None):
    paths = _report_paths(job_id)
    paths["job_dir"].mkdir(parents=True, exist_ok=True)
    paths["report"].write_text(json.dumps(result, indent=2), encoding="utf-8")
    meta = {"job_id": job_id, "config_name": config_name, "backend_job_id": backend_job_id}
    if assessment_id is not None:
        meta["assessment_id"] = assessment_id
    paths["meta"].write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _load_persisted(job_id):
    paths = _report_paths(job_id)
    if not paths["report"].exists():
        return None
    try:
        result = json.loads(paths["report"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    config_name = "Stored report"
    backend_job_id = None
    assessment_id = None
    if paths["meta"].exists():
        try:
            meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                if meta.get("config_name"):
                    config_name = str(meta["config_name"])
                backend_job_id = meta.get("backend_job_id")
                assessment_id = meta.get("assessment_id")
        except (OSError, ValueError):
            pass

    return {"status": "completed", "result": result, "config_name": config_name, "error": None, "backend_job_id": backend_job_id, "assessment_id": assessment_id}


# ---------------------------------------------------------------------------
# Job ID helpers
# ---------------------------------------------------------------------------

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


def _job_id_from_config(cfg):
    """Derive a stable job_id from the YAML config's MLflow identifiers.

    Priority:
    1. model.mlflow_run_id  — used verbatim if it looks safe for a URL segment
    2. run_id extracted from a runs:/<run_id>/... model URI
    3. Fallback: random UUID hex
    """
    try:
        model = cfg.get("model", {}) if isinstance(cfg, dict) else {}

        run_id = model.get("mlflow_run_id")
        if run_id and isinstance(run_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", run_id.strip()):
            return run_id.strip()

        model_uri = model.get("mlflow_model_uri") or ""
        if isinstance(model_uri, str):
            m = re.match(r"runs:/([a-zA-Z0-9_-]+)", model_uri)
            if m:
                return m.group(1)
    except Exception:
        pass
    return uuid.uuid4().hex


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


def _run_eval_job(job_id, config_name, temp_path, assessment_id=None):
    try:
        result, backend_job_id = _call_backend_api(config_name, temp_path)

        # Persist under the backend's job_id so all run files share one folder.
        persist_id = backend_job_id or job_id
        _persist_result(persist_id, config_name, result, backend_job_id=backend_job_id, assessment_id=assessment_id)
        _set_job(job_id, status="completed", result=result, error=None, backend_job_id=backend_job_id)

        if assessment_id:
            try:
                from trustworthiness.models import Assessment
                Assessment.objects.filter(id=assessment_id).update(
                    results=result, status=Assessment.Status.COMPLETED,
                )
            except Exception:
                logger.exception("Failed to save results for assessment_id=%s", assessment_id)

    except Exception as exc:
        error_message = str(exc)
        _set_job(job_id, status="failed", result=None, error=error_message)
        if assessment_id:
            try:
                from trustworthiness.models import Assessment
                Assessment.objects.filter(id=assessment_id).update(
                    status=Assessment.Status.FAILED, error_message=error_message,
                )
            except Exception:
                logger.exception("Failed to mark assessment_id=%s as failed", assessment_id)

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


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


def _create_assessment(user, project_id, input_data, parent_assessment=None):
    if not project_id:
        return None
    try:
        from projects.models import Project
        from trustworthiness.models import Assessment
        project = Project.objects.get(id=int(project_id))
        if not project.is_accessible_by(user):
            logger.warning("User %s denied access to project_id=%s for Assessment creation", user.id, project_id)
            return None
        return Assessment.objects.create(
            project=project,
            assessment_type=Assessment.AssessmentType.ROBUSTNESS,
            input_data=input_data,
            parent_assessment=parent_assessment,
            version=(parent_assessment.version + 1) if parent_assessment else 1,
        ).id
    except Exception:
        logger.exception("Failed to create Assessment for project_id=%s", project_id)
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


def _get_owned_assessment(user, assessment_id):
    from trustworthiness.models import Assessment
    assessment = get_object_or_404(
        Assessment, id=assessment_id, assessment_type=Assessment.AssessmentType.ROBUSTNESS,
    )
    if not assessment.project.is_accessible_by(user):
        logger.warning("User %s denied access to assessment_id=%s", user.id, assessment_id)
        raise Http404
    return assessment


@login_required
def config_input_view(request):
    if request.method == "POST":
        config_file = request.FILES.get("config_file")
        if not config_file:
            return _robustness_render(
                request,
                "robustness/config_input.html",
                {"error": "Please select a YAML configuration file before submitting."},
            )

        config_name = request.POST.get("config_name", "").strip() or Path(config_file.name).stem

        suffix = Path(config_file.name).suffix or ".yaml"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in config_file.chunks():
                tmp.write(chunk)

        parsed_config = _parse_yaml_config(tmp.name)
        job_id = _job_id_from_config(parsed_config)
        project_id = request.POST.get("project_id", "")

        parent_assessment = None
        parent_assessment_id = request.POST.get("parent_assessment_id", "").strip()
        if parent_assessment_id:
            try:
                parent_assessment = _get_owned_assessment(request.user, int(parent_assessment_id))
            except (ValueError, Http404):
                logger.warning(
                    "Invalid or inaccessible parent_assessment_id=%s for user %s; creating an unversioned assessment instead",
                    parent_assessment_id, request.user.id,
                )

        assessment_id = _create_assessment(request.user, project_id, {
            "config_name": config_name,
            "config_file": config_file.name,
            "config": parsed_config,
        }, parent_assessment=parent_assessment)
        _set_job(job_id, status="running", config_name=config_name, result=None, error=None, assessment_id=assessment_id)

        threading.Thread(
            target=_run_eval_job,
            args=(job_id, config_name, tmp.name),
            kwargs={"assessment_id": assessment_id},
            daemon=True,
        ).start()

        return redirect(f"{reverse('robustness:processing')}?job={job_id}")

    return _robustness_render(request, "robustness/config_input.html", {
        "project_id": request.GET.get("project_id", ""),
    })


@login_required
def processing_view(request):
    job_id = request.GET.get("job")
    if not job_id:
        return redirect("robustness:config_input")

    job = _get_job(job_id)
    if not job:
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

    config_name = job.get("config_name", "-")
    job_status = job.get("status")

    if job_status == "completed":
        return redirect("robustness:results", job_id=job_id)

    if job_status == "failed":
        assessment_id = job.get("assessment_id")
        if assessment_id:
            try:
                from trustworthiness.models import Assessment
                Assessment.objects.filter(id=assessment_id, status=Assessment.Status.RUNNING).update(
                    status=Assessment.Status.FAILED, error_message=job.get("error") or "Unknown evaluation error.",
                )
            except Exception:
                logger.exception("Failed to sync failed status for assessment_id=%s", assessment_id)
        return _robustness_render(
            request,
            "robustness/processing.html",
            {
                "job_id": job_id,
                "job_status": job_status,
                "analysis_error": job.get("error") or "Unknown evaluation error.",
                "config_name": config_name,
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
            "status_url": reverse("robustness:job_status"),
            "results_base_url": reverse("robustness:results", kwargs={"job_id": "__JOB_ID__"}).replace("__JOB_ID__/", ""),
        },
    )


@login_required
def job_status_api(request):
    job_id = request.GET.get("job")
    if not job_id:
        return JsonResponse({"status": "not_found"}, status=400)
    job = _get_job(job_id)
    if not job:
        return JsonResponse({"status": "not_found"}, status=404)
    return JsonResponse({
        "status": job.get("status"),
        "error": job.get("error"),
        "backend_job_id": job.get("backend_job_id"),
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
    job = _get_job(job_id) or _load_persisted(job_id)
    if not job:
        return _robustness_render(
            request,
            "robustness/results_report.html",
            {"job_id": job_id, "error": "Job not found. The server may have restarted since the evaluation ran."},
        )

    if job.get("status") != "completed":
        return redirect(f"{reverse('robustness:processing')}?job={job_id}")

    data = job.get("result") or {}
    assessment_id = job.get("assessment_id")
    if assessment_id:
        try:
            from trustworthiness.models import Assessment
            a = Assessment.objects.get(id=assessment_id)
            if a.results is None or a.status != Assessment.Status.COMPLETED:
                a.results = data
                a.status = Assessment.Status.COMPLETED
                a.save()
        except Exception:
            logger.exception("Failed to sync results for assessment_id=%s", assessment_id)

    context = {
        "job_id": job_id,
        "backend_job_id": job.get("backend_job_id"),
        "error": None,
        **_report_context_from_result(data),
    }
    return _robustness_render(request, "robustness/results_report.html", context)


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
    assessment = _get_owned_assessment(request.user, assessment_id)
    input_data = assessment.input_data or {}
    original_filename = input_data.get("config_file") or "config.yaml"
    yaml_text = _config_to_yaml_text(input_data)
    return _robustness_render(request, "robustness/config_input.html", {
        "mode": "edit",
        "parent_assessment_id": assessment.id,
        "project_id": assessment.project_id,
        "config_name": input_data.get("config_name", ""),
        "original_filename": original_filename,
        "ui_state": {"mode": "edit", "original_filename": original_filename, "yaml_text": yaml_text},
    })


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
        "error": None,
        **_report_context_from_result(assessment.results),
    }
    return _robustness_render(request, "robustness/results_report.html", context)


@login_required
def results_json_view(request, job_id):
    job = _get_job(job_id) or _load_persisted(job_id)
    if not job:
        return JsonResponse({"error": "Job not found."}, status=404)
    result = job.get("result") or {}
    response = JsonResponse(result, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = f'attachment; filename="robustness-report-{job_id}.json"'
    return response


@login_required
def list_adversarial_csvs_view(request, job_id):
    job = _get_job(job_id) or _load_persisted(job_id)
    if not job:
        return JsonResponse({"error": "Job not found."}, status=404)

    backend_job_id = job.get("backend_job_id")
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
def download_adversarial_csv_view(request, job_id, attack_key):
    job = _get_job(job_id) or _load_persisted(job_id)
    if not job:
        return JsonResponse({"error": "Job not found."}, status=404)

    backend_job_id = job.get("backend_job_id")
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
