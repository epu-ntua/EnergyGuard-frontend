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
| `digitaltwins` | Digital twin facility map and detail views |
| `questionnaire` | AI trustworthiness survey questionnaire (integrated app) |

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
├── digitaltwins/              # Digital twin facilities
├── questionnaire/             # Trustworthiness survey (also runnable standalone)
│   ├── manage.py
│   ├── requirements.txt
│   ├── questions.json         # Question bank for import
│   └── config/               # Standalone settings and URLs
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
python manage.py import_questions questions.json
python manage.py runserver 8001
```

## Environment Variables

Key variables required in `.env`:

| Variable | Description |
|----------|-------------|
| `PORT` | Host port for the web service (default: `8080`) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PostgreSQL credentials |
| `POSTGRES_HOST` / `POSTGRES_PORT` | PostgreSQL connection |
| `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` | PgAdmin login |
| `OIDC_RP_CLIENT_ID` / `OIDC_RP_CLIENT_SECRET` | Keycloak OIDC credentials |
| `KEYCLOAK_USER_SYNC_ID` / `KEYCLOAK_USER_SYNC_SECRET` | Keycloak user sync |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP email |
| `OBJECT_STORAGE_ENDPOINT` / `ACCESS_KEY` / `SECRET_KEY` | MinIO/S3 storage |
| `MEDIA_BUCKET` / `USE_S3_FOR_MEDIA` | Media storage configuration |
| `SCAN_API_URL` | Semgrep code analysis API |
| `ROBUSTNESS_API_URL` | Adversarial robustness testing API |
| `DATA_MANAGEMENT_SERVER_URL` | External data management service |
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

## Team Workflow

- Main platform changes stay in the root Django project.
- Questionnaire-specific changes stay under `questionnaire/`.
- Cross-service integration (if questionnaire runs standalone) should happen via URLs/API contracts, not by importing code between services.
