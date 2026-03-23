FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM golang:1.24 AS gobase

FROM python:3.12-slim

COPY --from=gobase /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && ln -s /root/.cargo/bin/cargo /usr/local/bin/cargo \
    && ln -s /root/.cargo/bin/rustup /usr/local/bin/rustup

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g wrangler

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

RUN uv venv && uv pip install --no-cache .

COPY --from=frontend /web/dist /app/static

ENTRYPOINT ["uv", "run", "autopilot"]
