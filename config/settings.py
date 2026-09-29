from pathlib import Path
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
]

SITE_ID = 1

MIDDLEWARE = [
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

AUTH_USER_MODEL = "accounts.User"     # custom user — set this BEFORE first migration

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT"),
        "CONN_MAX_AGE": 60,                 # reuse DB connections instead of reconnecting per request
        "CONN_HEALTH_CHECKS": True,         # drop dead connections (e.g. after network change)
        "OPTIONS": {"sslmode": "require"},  # Supabase requires SSL
    }
}

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

SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = env("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY", default="")
SUPABASE_STORAGE_BUCKET = env("SUPABASE_STORAGE_BUCKET", default="research-documents")

ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]