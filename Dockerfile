# One image, two roles:
#   web:    python -m fixtournament serve --host 0.0.0.0 --port 8000
#   worker: python -m fixtournament.worker < payload.json   (what each candidate's Serverless Job runs)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && chown -R app /app
USER app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8000
CMD ["sh", "-c", "python -m fixtournament serve --host 0.0.0.0 --port ${PORT:-8000}"]