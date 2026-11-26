# Kargonaut (Georgia) container. Not needed locally: `uvicorn server:app` works as it is.
# .env is NOT copied (.dockerignore): in the cloud GEMINI_API_KEY comes from the platform's secrets.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    KARGONAUT_SECURE_COOKIE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}
