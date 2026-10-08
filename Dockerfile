# Days of Cover deployment image.
# Build the Svelte technical preview and package it alongside the Python
# application. The container serves static files, the health endpoint,
# illustrative example endpoints and the bounded synchronous simulation API.

# ---- build the web front end ----
FROM node:22-slim AS webbuild
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN addgroup --system app && adduser --system --ingroup app --no-create-home app

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY --from=webbuild /web/dist ./src/daysofcover/web_static

RUN pip install .

USER app
EXPOSE 8000

CMD ["sh", "-c", "uvicorn daysofcover.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
