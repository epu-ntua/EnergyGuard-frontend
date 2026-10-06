# EnergyGuardPlatform

## Overview

EnergyGuard is a Django-based platform for AI trustworthiness assessment, project and dataset management, robustness testing, and digital twin exploration — built for European energy systems research.

## Architecture

### Docker Services

| Service | Description | Port |
|---------|-------------|------|
| `web` | Main Django application | `${PORT:-8080}` → 8000 |
| `db` | PostgreSQL 16 | internal |
| `qcluster` | Django-Q2 background task worker | internal |
| `pgadmin` | Database administration UI | `5051` |

### Django Apps

| App | Purpose |
|-----|---------|
| `core` | Shared base models, home page, dashboard, documentation |
| `accounts` | User auth, profiles, teams, invitations, notifications, Keycloak SSO |
| `datasets` | Dataset management with MinIO/S3 storage |
| `projects` | Project and experiment tracking with MLflow integration |
| `billing` | Billing records and payment methods |
| `code_analysis` | Static code trustworthiness scanning via Semgrep (GitHub, Jupyter, file upload) |
| `robustness` | AI robustness testing via external adversarial attack API |
| `trustworthiness` | Unified `Assessment` model tying together AI Act, code analysis and robustness results per project |
| `digitaltwins` | Digital twin facility map and detail views |
| `questionnaire` | AI trustworthiness survey questionnaire (integrated app) |
| `dataspace` | Gateway view for external dataspace connectors |

## Repository Structure

```text
EnergyGuardPlatform/
├── Dockerfile                 # Main app image
├── docker-compose.yml         # Orchestrates web, db, qcluster, pgadmin
├── requirements.txt           # Main app Python dependencies
├── manage.py
├── main/                      # Django project settings and root URLs
├── core/                      # Shared models, home, dashboard, docs
├── accounts/                  # Auth, profiles, teams, notifications
├── datasets/                  # Dataset management and storage
├── projects/                  # Projects and experiments
├── billing/                   # Billing and payments
├── code_analysis/             # Semgrep-based trustworthiness scanning
├── robustness/                # Adversarial robustness testing
├── trustworthiness/           # Unified Assessment model across AI Act/code analysis/robustness
├── digitaltwins/              # Digital twin facilities
├── questionnaire/             # Trustworthiness survey (also runnable standalone)
│   ├── manage.py
│   ├── requirements.txt
│   ├── questionnaire.json     # Question/step/item bank, read directly at runtime
│   └── config/               # Standalone settings and URLs
├── dataspace/                 # External dataspace connector gateway
├── static/                    # Frontend assets (CSS, JS, DataTables, TinyMCE)
└── media/                     # User-uploaded files
```

## Local Development

### Prerequisites

- Docker Desktop running

### Setup

1. Copy `.env` and fill in required values (see [Environment Variables](#environment-variables)):

2. Build and start all services:

```bash
docker compose up --build
```

3. Default URLs:
   - Main app: `http://localhost:8080`
   - PgAdmin: `http://localhost:5051`

### Questionnaire Standalone Mode

The `questionnaire` app is integrated into the main Django project. It can also be run as a standalone service:

```bash
cd questionnaire
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8001
```

Question/step/item content lives in `questionnaire/questionnaire.json` and is read directly at runtime (no import step required).

## Deployment

Deployment is `git pull` + restart on the server — the source tree is bind-mounted, and the same `docker-compose.yml` runs on both machines. The server adds an untracked `docker-compose.server.yml` overlay (for the nginx-proxy network) and sets `WEB_SERVER_CMD` in `.env` to run Gunicorn instead of `runserver`:

```bash
WEB_SERVER_CMD=gunicorn main.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers 1 --threads 8 --timeout 120
docker compose -f docker-compose.yml -f docker-compose.server.yml up -d
```

`--workers` must stay at `1`: `code_analysis` and `robustness` hold background-job state in module-level dicts, which is per-process, so extra worker processes would make the status poll miss the job. Raise the worker count only once those two apps move job state into the database.

## Environment Variables

Key variables required in `.env`:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Django debug flag |
| `PORT` | Host port for the web service (default: `8080`) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PostgreSQL credentials |
| `POSTGRES_HOST` / `POSTGRES_PORT` | PostgreSQL connection |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | PgAdmin login |
| `OIDC_RP_CLIENT_ID` / `OIDC_RP_CLIENT_SECRET` | Keycloak OIDC credentials |
| `KEYCLOAK_USER_SYNC_ID` / `KEYCLOAK_USER_SYNC_CLIENT_SECRET` | Keycloak user sync |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_SSL` / `DEFAULT_FROM_EMAIL` / `DJANGO_ADMINS` | SMTP email |
| `OBJECT_STORAGE_ENDPOINT` / `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` / `OBJECT_STORAGE_VERIFY_SSL` | MinIO/S3 storage |
| `OBJECT_STORAGE_BUCKET` / `OBJECT_STORAGE_BUCKET_SIMULATIONS` / `OBJECT_STORAGE_MEDIA_BUCKET` / `USE_S3_FOR_MEDIA` | Media/dataset storage configuration |
| `SCAN_API_URL` / `SCAN_API_TIMEOUT` | Semgrep code analysis API |
| `ROBUSTNESS_API_URL` / `ROBUSTNESS_API_TIMEOUT` / `ROBUSTNESS_API_SUBMIT_TIMEOUT` / `ROBUSTNESS_API_POLL_INTERVAL` / `ROBUSTNESS_API_POLL_TIMEOUT` | Adversarial robustness testing API |
| `DATA_MANAGEMENT_SERVER_URL` / `DATA_MANAGEMENT_SERVER_API_KEY` | External data management service |
| `DATASPACE_GATEWAY_URL` | Dataspace connector gateway |
| `DATALAKE_HOST` / `DATALAKE_PORT` / `DATALAKE_USER` / `DATALAKE_PASSWORD` / `DATALAKE_CONNECT_TIMEOUT` | Datalake connection |
| `PILOT_DATASETS_PREFIX` | Prefix used by the `seed_pilot_datasets` management command |
| `RDN_API_URL` / `RDN_API_USER_ID` / `RDN_API_EMAIL` / `RDN_API_PASSWORD` / `RDN_API_ORGANISATION` | RDN API integration |
| `CIEMAT_API_BASE_URL` / `CIEMAT_API_KEY` | CIEMAT API integration |
| `HAL_BASE_URL` | HAL API integration |
| `BER_EMAIL` | BER results notification sender |
| `JUPYTERHUB_URL` | JupyterHub integration |
| `MLFLOW_TRACKING_USERNAME` / `MLFLOW_TRACKING_PASSWORD` | MLflow experiment tracking |

## Tech Stack

- **Backend**: Django 6.0, Python 3.12
- **Database**: PostgreSQL 16 (main app), SQLite (questionnaire standalone)
- **Auth**: django-allauth + Keycloak OpenID Connect
- **Storage**: MinIO (S3-compatible) via boto3 + django-storages
- **Background tasks**: Django-Q2 (`qcluster` worker)
- **Frontend**: DataTables, TinyMCE, jQuery
- **Static files**: WhiteNoise
- **Production server**: Gunicorn

## External Integrations

- **Keycloak** — SSO and user federation
- **Semgrep** — Static analysis for code trustworthiness scans
- **Robustness API** — Adversarial attack testing for AI models
- **MLflow** — Experiment tracking within projects
- **JupyterHub** — Notebook-based code analysis source
- **Dataspace connectors** — External data gateway (`DATASPACE_GATEWAY_URL`)
- **RDN API** — Async external assessment integration (django_q self-rescheduling poll chain)
- **CIEMAT / HAL APIs** — External data/document sources
- **Datalake** — External datalake connection for dataset ingestion

## Team Workflow

- Main platform changes stay in the root Django project.
- Questionnaire-specific changes stay under `questionnaire/`.
- Cross-service integration (if questionnaire runs standalone) should happen via URLs/API contracts, not by importing code between services.
