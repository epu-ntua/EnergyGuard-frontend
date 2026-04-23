FROM python:3.11

RUN apt-get update && \
    apt-get install -y --no-install-recommends unzip curl git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY python_requirements.txt /app/
RUN pip install -r python_requirements.txt

COPY . /app

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]