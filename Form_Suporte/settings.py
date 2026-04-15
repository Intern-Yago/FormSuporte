"""
Django settings for Form_Suporte project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
from django.utils.translation import gettext_lazy as _

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
SETTINGS_DIR = Path(__file__).resolve().parent

# .env do Form_Suporte
load_dotenv(dotenv_path=SETTINGS_DIR / ".env")

# ===================== AMBIENTE =====================
# dev | prod
DJANGO_ENV = (os.getenv("DJANGO_ENV") or "dev").strip().lower()
IS_PROD = DJANGO_ENV in ("prod", "production")

# ===================== ODOO =====================
ODOO_URL = os.environ.get("ODOO_URL", "")
ODOO_DB = os.environ.get("ODOO_DB", "")
ODOO_USER = os.environ.get("ODOO_USER", "")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD") or os.environ.get("ODOO_PASS", "")

# ===================== SHOPIFY =====================
SHOPIFY_STORE_URL = os.environ.get("SHOPIFY_STORE_URL", "")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")

LOCALE_PATHS = [os.path.join(BASE_DIR, "locale")]

# ===================== SECURITY =====================
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Debug controlado por env (default: dev=1, prod=0)
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
if IS_PROD:
    DEBUG = False

ALLOWED_HOSTS = [
    "127.0.0.1",
    "0.0.0.0",
    "localhost",
    "*.ngrok-free.app",
    "*.ngrok-free.dev",
    "*",
    "82.25.71.76",
    "http://82.25.71.76",
    "http://127.0.0.1",
    "http://localhost",
]

CSRF_TRUSTED_ORIGINS = [
    "https://jodi-nonbathing-cherise.ngrok-free.dev",
    "http://82.25.71.76",
    "http://127.0.0.1",
    "http://0.0.0.0",
    "https://eaatainterno.duckdns.org",
]

# ===================== APPS =====================
INSTALLED_APPS = [
    "usuarios",
    "daphne",
    "channels",
    "corsheaders",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "painel",
    "form",
    "ocorrencia_erro",
    "API",
    "rest_framework",
    "rest_framework.authtoken",
    "simulador",
    "serial_vci",
    "situacao_veiculo.apps.SituacaoVeiculoConfig",
    "pedido",
    "storages",
    "clientes",
    "kpis"
]

ASGI_APPLICATION = "Form_Suporte.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(os.getenv("REDIS_HOST", ""), 6379)],
        },
    },
}

CORS_ALLOW_ALL_ORIGINS = True
APPEND_SLASH = True

URL_LOGIN = 'painel_home'

# ==========================================================
# PAINEL – CONTROLE DE SISTEMAS
# ==========================================================

PAINEL_SYSTEMS = {
    "ocorrencia": {"name": "Ocorrências", "setor": "suporte", "url": "/"},
    "situacao": {"name": "Situação (Serial)", "setor": "suporte", "url": "/situacao/"},
    "seriais": {"name": "Seriais VCI", "setor": "suporte", "url": "/seriais/"},
    "form": {"name": "Form (Veículos)", "setor": "suporte", "url": "/form/"},
    "simulador": {"name": "Simulador", "setor": "comercial", "url": "/simulador/"},
    "pedido": {"name": "Pedidos", "setor": "comercial", "url": "/pedido/"},
    "clientes": {"name": "Clientes (Odoo/Shopify)", "setor": "comercial", "url": "/clientes/"},
    "api": {"name": "API", "setor": "ti", "url": "/api/"},
    "blockunblock": {
        "name": "BlockUnblock",
        "setor": "financeiro",
        "url": "/painel/sso/blockunblock/",
    }
}

PAINEL_MODULE_AREAS = {
    "ocorrencia_erro": "suporte",
    "situacao_veiculo": "suporte",
    "simulador": "comercial",
    "serial_vci": "suporte",
    "form": "suporte",
    "pedido": "comercial",
    "API": "ti",
}

PAINEL_SETOR_DEFAULT_ACCESS = {
    "suporte": {"suporte", "comercial"},
    "financeiro": {"financeiro", "comercial"},
    "comercial": {"comercial"},
    "marketing": {"marketing", "comercial"},
    "ti": {"suporte", "financeiro", "comercial", "marketing", "ti"},
}

# ===================== MIDDLEWARE =====================
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Form_Suporte.urls"

# ===================== TEMPLATES =====================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "painel.context_processsors.painel_modules",
            ],
        },
    },
]

# ===================== DATABASE =====================
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DB_NAME", os.path.join(BASE_DIR, "db.sqlite3")),
        "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", ""),
        "PORT": os.getenv("DB_PORT", ""),
    }
}

# ===================== AUTH VALIDATORS =====================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ===================== I18N =====================
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = (
    ("pt-br", _("Portuguese")),
    ("es", _("Spanish")),
)

# ===================== STATIC =====================
STATIC_URL = "/static/"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# ===================== MinIO / S3 =====================
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "https://eaatamin.ddns.net")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

# 1 bucket por ambiente
MINIO_BUCKET_MAIN = os.getenv("MINIO_BUCKET_MAIN", "eaata-prod" if IS_PROD else "eaata-dev")

AWS_ACCESS_KEY_ID = MINIO_ACCESS_KEY
AWS_SECRET_ACCESS_KEY = MINIO_SECRET_KEY
AWS_STORAGE_BUCKET_NAME = MINIO_BUCKET_MAIN
AWS_S3_ENDPOINT_URL = MINIO_ENDPOINT
AWS_S3_REGION_NAME = MINIO_REGION

AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_S3_ADDRESSING_STYLE = "path"
AWS_DEFAULT_ACL = None

# False = URL direta sem assinatura
AWS_QUERYSTRING_AUTH = (os.getenv("AWS_QUERYSTRING_AUTH", "0") == "1")

# ✅ Default = ocorrencias (prefixo dentro do bucket único)
STORAGES = {
    "default": {
        "BACKEND": "utils.storages.OcorrenciasStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# URL base do bucket
MEDIA_URL = f"{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/"

# ===================== DRF =====================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle"
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/day",
        "user": "1000/day"
    }
}

# ===================== DEFAULTS =====================
SITUACAO_WEBHOOK_TOKEN = os.getenv("SITUACAO_WEBHOOK_TOKEN")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ================================
# REDE (SANDBOX)
# ================================
REDE_SANDBOX = os.getenv("REDE_SANDBOX")
REDE_CLIENT_ID = os.getenv("REDE_CLIENT_ID")
REDE_CLIENT_SECRET = os.getenv("REDE_CLIENT_SECRET")
REDE_WEBHOOK_REGISTER_IN_SANDBOX = os.getenv("REDE_WEBHOOK_REGISTER_IN_SANDBOX")
REDE_WEBHOOK_USE_AUTH = os.getenv("REDE_WEBHOOK_USE_AUTH")
REDE_WEBHOOK_AUTH_TOKEN = os.getenv("REDE_WEBHOOK_AUTH_TOKEN")
REDE_WEBHOOK_AUTH_ENABLED = os.getenv("REDE_WEBHOOK_AUTH_ENABLED")

# ================================
# BLOCKUNBLOCK
# ================================
BLOCK_UNBLOCK_BASE_URL = os.getenv("BLOCK_UNBLOCK_BASE_URL")
BLOCK_UNBLOCK_FRONTEND_URL= os.getenv("BLOCK_UNBLOCK_FRONTEND_URL")
BLOCK_UNBLOCK_SSO_URL=os.getenv("BLOCK_UNBLOCK_SSO_URL")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:9000")