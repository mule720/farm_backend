from pathlib import Path
from datetime import timedelta
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY', default='django-insecure-3txn=-s=q^ou57(m=$5f8wjdsw9uu@dy)rq4pazzi8qsug9-$a')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'graphene_django',
    'graphql_jwt.refresh_token',
    'corsheaders',
    'django_filters',
    'django_celery_beat',
    'django_celery_results',

    # Domain apps (one per functionality)
    'apps.accounts',
    'apps.enterprises',
    'apps.forms_engine',
    'apps.kpis',
    'apps.automation',
    'apps.inventory',
    'apps.production',
    'apps.intelligence',
    'apps.dashboard',
    'apps.devices',
    'apps.plans',
    'apps.vision',
    'apps.irrigation',
    'apps.equipment',
    'apps.tracking',
    'apps.market',
    'apps.weather',
    'apps.sustainability',
    'apps.financials',
    'apps.greenhouse',
    'apps.labor',
    'apps.notifications',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
}
DATABASES['default']['CONN_MAX_AGE'] = 60

# Custom user model
AUTH_USER_MODEL = 'accounts.Profile'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lusaka'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Django 5.1 STORAGES dict (replaces deprecated STATICFILES_STORAGE / DEFAULT_FILE_STORAGE)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── GraphQL ─────────────────────────────────────────────────────────────────
GRAPHENE = {
    'SCHEMA': 'config.schema.schema',
    'MIDDLEWARE': [
        'graphql_jwt.middleware.JSONWebTokenMiddleware',
    ],
}

AUTHENTICATION_BACKENDS = [
    'graphql_jwt.backends.JSONWebTokenBackend',
    'django.contrib.auth.backends.ModelBackend',
]

GRAPHQL_JWT = {
    'JWT_VERIFY_EXPIRATION': True,
    'JWT_LONG_RUNNING_REFRESH_TOKEN': True,
    'JWT_EXPIRATION_DELTA': timedelta(hours=8),
    'JWT_REFRESH_EXPIRATION_DELTA': timedelta(days=30),
    'JWT_SECRET_KEY': env('JWT_SIGNING_KEY', default=SECRET_KEY),
    'JWT_ALGORITHM': 'HS256',
}

# ─── CORS ────────────────────────────────────────────────────────────────────
if DEBUG:
    # Allow any origin in dev — the frontend IP changes on WSL2/network interfaces
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = env.list(
        'CORS_ALLOWED_ORIGINS',
        default=[
            'http://localhost:8080',
            'http://localhost:8081',
            'http://localhost:5173',
            'http://localhost:19006',
        ],
    )
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization',
    'content-type', 'dnt', 'origin', 'user-agent',
    'x-csrftoken', 'x-requested-with',
]

# ─── Celery ──────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# ─── Email ───────────────────────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='AgroNexus <noreply@agronexus.io>')

SUPABASE_JWT_SECRET = env('SUPABASE_JWT_SECRET', default='')

# ─── File Storage ─────────────────────────────────────────────────────────────
# In production, media files go to Google Cloud Storage so they survive pod restarts.
# Requires: django-storages[google] in requirements.txt
# Set GCS_MEDIA_BUCKET env var to your GCS bucket name.
if not DEBUG:
    GS_BUCKET_NAME = env('GCS_MEDIA_BUCKET', default='')
    GS_DEFAULT_ACL = None          # uniform bucket-level access — no per-object ACLs
    MEDIA_URL = f'https://storage.googleapis.com/{GS_BUCKET_NAME}/'
    # Override default storage backend to GCS (Django 5.1 STORAGES dict)
    STORAGES["default"]["BACKEND"] = "storages.backends.gcloud.GoogleCloudStorage"

# ─── Security (production hardening) ─────────────────────────────────────────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = False    # GKE Ingress handles TLS termination
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
