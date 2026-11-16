# syntax=docker/dockerfile:1

# ---- build stage: install dependencies into a virtualenv -----------------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime stage: just Python, the venv and the code --------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --chown=app:app . .

# Collect admin and API-docs assets at build time; whitenoise serves them.
RUN DJANGO_DEBUG=false DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && chmod +x docker/entrypoint.sh

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health/')"

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["web"]
