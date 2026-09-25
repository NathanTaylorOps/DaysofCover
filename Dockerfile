# Days of Cover -- Stage 0 image.
#
# Two stages: build the Svelte placeholder page with Node (never installed
# on the dev machine -- see the build plan's "Machine" note), then install
# the Python package with that build baked in as static files. Nothing in
# here is what a real release looks like yet -- no engine, no job runner,
# no real UI -- this exists so `docker run` serves a real page with zero
# toolchain and Render has something to pull (Stage 0 acceptance criteria).

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
