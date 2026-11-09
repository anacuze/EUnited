"""
Django settings for the EUnited project.

Development defaults: a local PostgreSQL database (see docker-compose.yml) and emails
printed to the console. For production, set the environment variables listed in README.md.
"""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Production is recognised by DJANGO_SECRET_KEY being set. Without it the project runs in
# development mode (debug on, insecure key). With it, debug is off unless DJANGO_DEBUG=1,
# so forgetting DJANGO_DEBUG on the server can't leave debug pages switched on.
_secret_key_from_env = os.environ.get("DJANGO_SECRET_KEY", "")
SECRET_KEY = _secret_key_from_env or "dev-only-insecure-key-change-me-before-deploying"
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if _secret_key_from_env else "1") == "1"
if not DEBUG and not _secret_key_from_env:
    raise ImproperlyConfigured("DJANGO_DEBUG=0 needs DJANGO_SECRET_KEY to be set (see README).")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # EUnited apps
    "accounts",
    "pulse",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "eunited.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pulse.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "eunited.wsgi.application"

# PostgreSQL in development too, so nothing behaves differently once the site is live.
# Without DATABASE_URL it connects to the local database from docker-compose.yml.
DATABASES = {
    "default": dj_database_url.config(
        default="postgres://eunited:eunited@localhost:5432/eunited",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "pulse:feed"
LOGOUT_REDIRECT_URL = "pulse:feed"

LANGUAGE_CODE = "en"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Emails (account confirmation, reminders) are printed in the terminal during development.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "EUnited <no-reply@eunited.local>")

# Public address of the site, used for links in emails sent outside a web request (reminders).
SITE_URL = os.environ.get("DJANGO_SITE_URL", "http://localhost:8000")

# --- EUnited settings ---------------------------------------------------------
# How many days ahead the "Closing soon" strip looks.
PULSE_CLOSING_SOON_DAYS = 7
# Reminders are sent this many days before a deadline or event start.
PULSE_REMINDER_DAYS = [3, 1]
# Posts per page in the feed.
PULSE_PAGE_SIZE = 12
