FROM node:22-slim AS web
WORKDIR /web
COPY dashboard/web/package.json dashboard/web/package-lock.json ./
RUN npm ci
COPY dashboard/web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --extra server --extra postgres
COPY configs ./configs
COPY scenarios ./scenarios
COPY rubrics ./rubrics
COPY cassettes ./cassettes
COPY baselines ./baselines
COPY results ./results
COPY labels ./labels
COPY docker/entrypoint.sh /entrypoint.sh
COPY --from=web /web/dist ./dashboard/web/dist
RUN chmod +x /entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
