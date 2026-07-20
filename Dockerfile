FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CROSSBORDER_APP_MODE=demo \
    CROSSBORDER_STATE_DB=/app/state/crossborder_state.db \
    CROSSBORDER_DEMO_SESSION_TTL=3600 \
    PORT=8000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements.txt README.md ./
COPY crossborder_analytics/ crossborder_analytics/
COPY crossborder_api/ crossborder_api/
COPY data/ data/
RUN python -m pip install --no-cache-dir .
COPY --from=frontend-build /app/frontend/dist frontend/dist
VOLUME ["/app/state"]
EXPOSE 8000
CMD ["uvicorn", "crossborder_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
