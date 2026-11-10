#!/bin/sh
# Runs every time the "web" container starts, before the server:
# creates or updates the tables, and loads the sample data the first time.
set -e

python manage.py migrate --noinput

if [ "$EUNITED_SEED_DEMO" = "1" ]; then
    # Only when there are no users yet, so your own changes are never overwritten.
    if ! python manage.py shell -c "import sys; from accounts.models import User; sys.exit(0 if User.objects.exists() else 1)" >/dev/null 2>&1; then
        python manage.py seed_demo
    fi
fi

exec "$@"
