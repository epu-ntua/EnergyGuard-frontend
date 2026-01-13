# Latest stable Python
FROM python:3.12-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System deps (Postgres client + build tools)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libpq-dev \
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
