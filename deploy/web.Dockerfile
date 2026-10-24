# The web image: the built frontend plus the FastAPI app. Build from the repo
# root (deploy/compose.yaml does): docker build -f deploy/web.Dockerfile .
# The same image runs web, worker and migrate.

FROM node:20 AS frontend
WORKDIR /build
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund --loglevel=error
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ARG SD_WEB_UID
ARG SD_WEB_GID
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# Installs the dependencies; PYTHONPATH then runs the code (with its data files,
# such as the migrations) straight from /app/src.
RUN pip install --no-cache-dir ".[web]"
COPY --from=frontend /build/dist /app/static
USER ${SD_WEB_UID}:${SD_WEB_GID}
EXPOSE 8000
CMD ["uvicorn", "sdweb.app:create_app_from_env", "--factory", "--host", "0.0.0.0", \
     "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
