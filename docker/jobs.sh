#!/bin/sh
# The background jobs a server would run with cron:
#   - reminders: every 10 minutes
#   - importer:  when the container starts, then every hour

# Wait until the "web" container has created the tables.
until python manage.py migrate --check >/dev/null 2>&1; do
    sleep 3
done

minutes=0
while true; do
    if [ $((minutes % 60)) -eq 0 ]; then
        python manage.py import_posts || echo "import_posts failed, trying again in an hour"
    fi
    python manage.py send_reminders || echo "send_reminders failed, trying again in 10 minutes"
    sleep 600
    minutes=$((minutes + 10))
done
