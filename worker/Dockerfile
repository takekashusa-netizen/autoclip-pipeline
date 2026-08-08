FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt
COPY . .
RUN chmod +x run_pipeline.sh skills/*.sh skills/*/run.sh
CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
