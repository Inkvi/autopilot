FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN uv venv && uv pip install --no-cache .

COPY --from=frontend /web/dist /app/static

ENTRYPOINT ["uv", "run", "autopilot"]
