FROM python:3.12-slim
WORKDIR /app
COPY requirements-serve.txt .
RUN pip install --no-cache-dir -r requirements-serve.txt
RUN useradd --create-home --uid 10001 appuser
COPY triage.py main.py queues.json ./
USER appuser
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
