# Latest stable Python
FROM python:3.12-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps (Postgres client + build tools). pg_dump for the nightly backup
# (core.tasks.backup_database) comes from the PostgreSQL apt repository, in the
# major version of the db service: Debian ships another, and a dump is only
# guaranteed to restore with the version that made it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       gcc \
       libpq-dev \
       postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy project
COPY . .

# Collect static at build time (safe with WhiteNoise)
# RUN python manage.py collectstatic --noinput

# Expose Django port
EXPOSE 8000

# Default command (overridden by docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
