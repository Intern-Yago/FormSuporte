#!/usr/bin/env bash
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo ">>> Running migrations..."
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-0}" = "1" ]; then
  echo ">>> Collecting static..."
  python manage.py collectstatic --noinput
fi

echo ">>> Starting server..."
: "${DJANGO_WSGI_MODULE:=Form_Suporte.wsgi:application}"  # <-- TROQUE AQUI pelo seu wsgi real

exec gunicorn "$DJANGO_WSGI_MODULE" \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${GUNICORN_WORKERS:-3} \
  --timeout ${GUNICORN_TIMEOUT:-120} \
  --access-logfile - \
  --error-logfile -
