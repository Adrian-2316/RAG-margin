# 1. Build the React front end
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# 2. Python app, run as an unprivileged user
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY margin/ margin/
COPY seed_docs/ seed_docs/
COPY --from=web /web/dist web/dist
RUN uv sync --frozen --no-dev && useradd --uid 10001 --no-create-home margin
USER margin
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "margin.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
