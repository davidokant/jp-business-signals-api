FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    APP_DATABASE_PATH=/app/data/production.db \
    APP_AUTO_SEED_SAMPLE=false

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system .

RUN mkdir -p /app/data
EXPOSE 8000

CMD ["sh", "-c", "uvicorn jp_business_signals.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
