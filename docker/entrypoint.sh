#!/bin/sh
# One image, several roles: `web`, `worker`, or any other command.
set -e

case "$1" in
  web)
    # Fine for a single web instance. With several, run migrations as a
    # separate release step instead so they never race.
    python manage.py migrate --noinput
    exec gunicorn config.wsgi:application -c gunicorn.conf.py
    ;;
  worker)
    exec celery -A config worker --loglevel=info --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  *)
    exec "$@"
    ;;
esac
