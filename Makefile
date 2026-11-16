PY ?= .venv/bin/python

.PHONY: install migrate run worker test seed up down logs webhook

install:            ## create a virtualenv and install dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

migrate:
	$(PY) manage.py migrate

run:                ## dev server on http://localhost:8000
	$(PY) manage.py runserver

worker:             ## Celery worker (needs Redis)
	.venv/bin/celery -A config worker --loglevel=info

test:
	.venv/bin/pytest

seed:               ## 200 demo calls over the last 14 days
	$(PY) manage.py seed --calls 200 --days 14 --flush

up:                 ## full stack: web, worker, postgres, redis
	docker compose up --build -d
	docker compose exec web python manage.py seed --flush

down:
	docker compose down

logs:
	docker compose logs -f web worker

webhook:            ## send one signed sample event to the local API
	$(PY) scripts/send_event.py
