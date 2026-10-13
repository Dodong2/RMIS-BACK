from pathlib import Path

from corsheaders.defaults import default_headers
from datetime import timedelta
import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()

# Local dev reads .env; inside Docker there is no .env file —
# values come from the Dokploy Environment tab instead.
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)

# e.g. ALLOWED_HOSTS=127.0.0.1,localhost,.trycloudflare.com
# The leading dot on .trycloudflare.com accepts ANY random quick-tunnel subdomain,
# so the backend never needs changing when the tunnel URL changes.
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

# e.g. CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "daphne",                        # first: its runserver serves ASGI (HTTP + WebSockets) in local dev
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",          # required by allauth/dj-rest-auth registration

    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",   # required: dj_rest_auth.registration imports its models even if unused
    "dj_rest_auth",
    "dj_rest_auth.registration",
    "channels",

    "accounts",
    "research_projects",
    "personnel",
    "budget_lib",
    "financial_monitoring",
    "compliance",
    "document_management",
    "outputs",
    "monitoring",
    "dashboard",
    "forecasting",
    "decision_support",
    "risk_indicators",
    "reports",
    "budget_sync",
    "realtime",
]

SITE_ID = 1

MIDDLEWARE = [
    "config.client_ip.CloudflareClientIPMiddleware",   # first: real client IP behind the CF tunnel (config/client_ip.py)
    "corsheaders.middleware.CorsMiddleware",   # must be near the top
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # serves /static/ (admin, DRF pages) without nginx
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",   # required by allauth even if unused directly
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Real-time signals (realtime/notify.py). In-memory by default: production runs ONE Daphne process, so every browser
# socket lives in the same process as the views that send. Setting REDIS_URL switches to Redis, needed only for
# several processes or for signals sent from a management command/cron (also needs channels-redis installed).
REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [REDIS_URL]}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

AUTH_USER_MODEL = "accounts.User"     # custom user — set this BEFORE first migration

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT"),
        # 0 = close after each request. Under ASGI (Daphne) sync views run on worker threads, and persistent
        # connections held per thread are never cleaned up, which would leak connections to the Supabase pooler.
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,         # drop dead connections (e.g. after network change)
        "OPTIONS": {"sslmode": "require"},  # Supabase requires SSL
    }
}

# Same as Django's default, written out so it's clear: per-process memory, no Redis. Production runs ONE Daphne
# process, so DRF throttle counters kept here are accurate.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cloudflare Tunnel terminates HTTPS and forwards plain HTTP to the container.
# This header tells Django the original request was HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# With DEBUG=False Django's default config only e-mails 500 tracebacks to ADMINS (none set), so they never
# reached `docker logs`. Send them, and our own app loggers, to stdout.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # Concurrent-write conflicts (unique race, deadlock) become 409 instead of 500 (config/concurrency.py).
    "EXCEPTION_HANDLER": "config.concurrency.conflict_exception_handler",
    # Throttling identifies clients by REMOTE_ADDR only (set from CF-Connecting-IP, config/client_ip.py), never by the
    # client-writable X-Forwarded-For.
    "NUM_PROXIES": 0,
}

BREVO_API_KEY = env("BREVO_API_KEY")
BREVO_SENDER_EMAIL = env("BREVO_SENDER_EMAIL")
BREVO_SENDER_NAME = env("BREVO_SENDER_NAME")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

REST_AUTH = {
    "USE_JWT": True,
    "JWT_AUTH_HTTPONLY": False,   # simplest for polyrepo/cross-domain
    "USER_DETAILS_SERIALIZER": "accounts.serializers.CustomUserDetailsSerializer",
    "LOGIN_SERIALIZER": "accounts.serializers.EmailLoginSerializer",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
}

# Exact-string match incl. scheme, no trailing slash:
# CORS_ALLOWED_ORIGINS=http://localhost:5173,https://rmis.netlify.app
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
# The frontend sends Idempotency-Key on create forms (config/concurrency.py); a cross-origin preflight must allow it.
CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key")

SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = env("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY", default="")
SUPABASE_STORAGE_BUCKET = env("SUPABASE_STORAGE_BUCKET", default="research-documents")

ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]