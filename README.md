# EnergyGuardPlatform

## Overview
This repository contains the main EnergyGuard Django application and a separate Django service for the trustworthiness questionnaire.

The goal is to keep the existing platform stable while allowing the questionnaire to evolve independently.

## Architecture

- `web`: main EnergyGuard Django application (existing codebase)
- `questionnaire`: separate Django service for trustworthiness survey flows
- `db`: shared PostgreSQL instance (currently used by `web`)
- `pgadmin`: database administration UI
- `minio` + `minio-init`: object storage and bucket bootstrap

## Repository Structure

```text
EnergyGuardPlatform/
|- Dockerfile                    # Main app (web) image
|- docker-compose.yml            # Orchestrates all services
|- accounts/ ...                 # Existing main app modules
|- core/ ...                     # Existing main app modules
|- datasets/ ...                 # Existing main app modules
|- projects/ ...                 # Existing main app modules
`- questionnaire/                # Separate questionnaire service
   |- Dockerfile
   |- requirements.txt
   |- manage.py
   `- config/
```

## Local Development

1. Ensure Docker Desktop is running.
2. From repository root, start services:

```bash
docker compose up --build
```

3. Default URLs:
- Main app: `http://localhost:8000`
- Questionnaire service: `http://localhost:8001`
- PgAdmin: `http://localhost:5050`
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

## Questionnaire Service Notes

- The `questionnaire` folder is intentionally isolated from the main Django project.
- Add questionnaire-specific apps (for example `trust`) inside this service only.
- Keep dependencies in `questionnaire/requirements.txt` to avoid coupling with the main app.
- Current default DB for `questionnaire` is SQLite (`questionnaire/config/settings.py`).
- If needed, switch `questionnaire` to Postgres using `POSTGRES_*` env variables in `.env`.

## Team Workflow

- Main platform changes stay in the root Django project.
- Trustworthiness questionnaire changes stay under `questionnaire/`.
- Cross-service integration should happen via URLs/API contracts, not by importing code between services.
