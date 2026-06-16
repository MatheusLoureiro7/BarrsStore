from pathlib import Path
import os
import logging
import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent

from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')

DEBUG = os.environ.get('DEBUG', 'False') == 'True'

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-local-dev-only-change-me'
    else:
        raise ImproperlyConfigured('Configure SECRET_KEY nas variaveis de ambiente.')

SENTRY_DSN = os.environ.get('SENTRY_DSN', '').strip()
if SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            send_default_pii=False,
            traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.05')),
            environment=os.environ.get('SENTRY_ENVIRONMENT', 'production' if not DEBUG else 'local'),
        )
    except ImportError:
        if not DEBUG:
            raise

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'ALLOWED_HOSTS',
        'barrsstore.com.br,www.barrsstore.com.br,web-production-c4971.up.railway.app,localhost,127.0.0.1,.ngrok-free.dev,.ngrok-free.app'
    ).split(',')
    if host.strip()
]

SITE_URL = os.environ.get('SITE_URL', 'https://www.barrsstore.com.br').rstrip('/')
GOOGLE_ANALYTICS_ID = os.environ.get('GOOGLE_ANALYTICS_ID', '').strip()
GOOGLE_SITE_VERIFICATION = os.environ.get('GOOGLE_SITE_VERIFICATION', '').strip()
META_PIXEL_ID = os.environ.get('META_PIXEL_ID', '').strip()
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN', '').strip()
META_TEST_EVENT_CODE = os.environ.get('META_TEST_EVENT_CODE', '').strip()
WHATSAPP_API_URL = os.environ.get('WHATSAPP_API_URL', '').strip().rstrip('/')
WHATSAPP_API_KEY = os.environ.get('WHATSAPP_API_KEY', '').strip()
WHATSAPP_INSTANCE = os.environ.get('WHATSAPP_INSTANCE', 'loja').strip() or 'loja'

ERP_WEBHOOK_URL = os.environ.get('ERP_WEBHOOK_URL', '')
ERP_WEBHOOK_TOKEN = os.environ.get('ERP_WEBHOOK_TOKEN', '')

LALAMOVE_API_KEY        = os.environ.get('LALAMOVE_API_KEY', '')
LALAMOVE_API_SECRET     = os.environ.get('LALAMOVE_API_SECRET', '')
LALAMOVE_SANDBOX        = os.environ.get('LALAMOVE_SANDBOX', 'True') == 'True'
LALAMOVE_ORIGIN_LAT     = os.environ.get('LALAMOVE_ORIGIN_LAT', '')
LALAMOVE_ORIGIN_LNG     = os.environ.get('LALAMOVE_ORIGIN_LNG', '')
LALAMOVE_ORIGIN_ADDRESS = os.environ.get('LALAMOVE_ORIGIN_ADDRESS', '')

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS',
        'https://web-production-c4971.up.railway.app,https://barrsstore.com.br,https://www.barrsstore.com.br,https://*.ngrok-free.dev,https://*.ngrok-free.app'
    ).split(',')
    if origin.strip()
]

INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sitemaps',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary',
    'cloudinary_storage',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'loja.apps.LojaConfig',
]

MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'loja.middleware.BlockScannerPathsMiddleware',
    'loja.middleware.AdminRateLimitMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'loja.middleware.CaptureUtmMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'loja.middleware.ContentSecurityPolicyReportOnlyMiddleware',
]

ROOT_URLCONF = 'barrs_store.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'loja.context_processors.marketing_tags',
            ],
            'libraries': {
                'inline_static': 'loja.templatetags.inline_static',
            },
        },
    },
]

WSGI_APPLICATION = 'barrs_store.wsgi.application'

# Banco de dados
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Cache — usa Redis se REDIS_URL valida estiver configurada, senao LocMem
_redis_url = os.environ.get('REDIS_URL', '')
_use_redis = not DEBUG and _redis_url.startswith(('redis://', 'rediss://', 'unix://'))
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': _redis_url,
    } if _use_redis else {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'barrs-store',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# Arquivos estáticos
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
WHITENOISE_MAX_AGE = 31536000
# Default seguro: True só em DEBUG (em prod, busca em finders a cada request é lenta).
WHITENOISE_USE_FINDERS = os.environ.get('WHITENOISE_USE_FINDERS', 'True' if DEBUG else 'False') == 'True'

# Cloudinary
import cloudinary
import cloudinary.uploader
import cloudinary.api

CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL', '').strip()
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '').strip()
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '').strip()
CLOUDINARY_API_SECRET = (
    os.environ.get('CLOUDINARY_API_SECRET', '').strip()
    or os.environ.get('CLOUDINARY_SECRET', '').strip()
)

if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)
    parsed_cloudinary = urlparse(CLOUDINARY_URL)
    CLOUDINARY_CLOUD_NAME = CLOUDINARY_CLOUD_NAME or parsed_cloudinary.hostname or ''
    CLOUDINARY_API_KEY = CLOUDINARY_API_KEY or parsed_cloudinary.username or ''
    CLOUDINARY_API_SECRET = CLOUDINARY_API_SECRET or parsed_cloudinary.password or ''
else:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': CLOUDINARY_CLOUD_NAME,
    'API_KEY': CLOUDINARY_API_KEY,
    'API_SECRET': CLOUDINARY_API_SECRET,
}

STORAGES = {
    "default": {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── SEGURANÇA ─────────────────────────────────────────────────────
# Settings comuns a dev e prod.
SECURE_REFERRER_POLICY = 'same-origin'
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME', 'barrs_sessionid_v2')
CSRF_COOKIE_NAME = os.environ.get('CSRF_COOKIE_NAME', 'barrs_csrftoken_v2')
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False' if DEBUG else 'True') == 'True'

# Email
EMAIL_BACKEND = (
    'django.core.mail.backends.console.EmailBackend'
    if DEBUG else
    'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = 'Barrs Store <noreply@barrsstore.com.br>'

# Settings exclusivos de produção: HSTS, cookies Secure, XSS filter, etc.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_BROWSER_XSS_FILTER = True
CONTENT_SECURITY_POLICY = os.environ.get(
    'CONTENT_SECURITY_POLICY',
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    # Sem 'unsafe-inline' (nonces cobrem todos os scripts inline proprios).
    # 'unsafe-eval' mantido pois o SDK do Mercado Pago precisa.
    "script-src 'self' 'nonce-{nonce}' 'unsafe-eval' https://sdk.mercadopago.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mercadolibre.com https://*.mercadolibre.com.br https://*.mlstatic.com https://connect.facebook.net https://www.googletagmanager.com https://www.google-analytics.com https://challenges.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mlstatic.com; "
    "font-src 'self' data: https://fonts.gstatic.com https://*.mlstatic.com; "
    "img-src 'self' data: blob: https://res.cloudinary.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mercadolibre.com https://*.mercadolibre.com.br https://*.mlstatic.com https://www.facebook.com https://www.google-analytics.com https://www.googletagmanager.com; "
    "connect-src 'self' https://api.mercadopago.com https://*.mercadopago.com https://*.mercadopago.com.br https://*.mercadolibre.com https://*.mercadolibre.com.br https://*.mlstatic.com https://viacep.com.br https://www.facebook.com https://graph.facebook.com https://www.google-analytics.com https://analytics.google.com https://challenges.cloudflare.com; "
    "frame-src 'self' https://*.mercadopago.com https://*.mercadopago.com.br https://*.mercadolibre.com https://*.mercadolibre.com.br https://www.mercadopago.com https://www.mercadopago.com.br https://challenges.cloudflare.com; "
    "worker-src 'self' blob:; "
    "form-action 'self' https://*.mercadopago.com https://www.mercadopago.com https://www.mercadopago.com.br"
).strip()
# Default seguro: enforce em prod automaticamente; dev fica em report-only para
# permitir debugar violacoes sem quebrar o site.
CSP_ENFORCE = os.environ.get('CSP_ENFORCE', 'False' if DEBUG else 'True') == 'True'
CONTENT_SECURITY_POLICY_REPORT_ONLY = CONTENT_SECURITY_POLICY if not CSP_ENFORCE else ''

TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY', '').strip()
TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '').strip()
TURNSTILE_REQUIRED = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)

if not DEBUG:
    # Compartilha os cookies entre barrsstore.com.br e www.barrsstore.com.br.
    # Isso evita falha de CSRF quando o cliente navega entre as duas versões do domínio.
    SESSION_COOKIE_DOMAIN = os.environ.get('SESSION_COOKIE_DOMAIN', '.barrsstore.com.br')
    CSRF_COOKIE_DOMAIN = os.environ.get('CSRF_COOKIE_DOMAIN', '.barrsstore.com.br')

# Limitar tentativas de login (proteção brute force)
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']
ADMIN_RATE_LIMIT = os.environ.get('ADMIN_RATE_LIMIT', '60/5m')

# Sessão expira ao fechar o browser? Não — mantemos por 14 dias para reduzir fricção.
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 dias

JAZZMIN_SETTINGS = {
    "site_title": "Barrs Store Admin",
    "site_header": "Barrs Store",
    "site_brand": "💎 Barrs Store",
    "welcome_sign": "Bem-vinda ao painel da Barrs Store",
    "copyright": "Barrs Store © 2026",
    "search_model": ["loja.Produto", "loja.Pedido"],
    "topmenu_links": [
        {"name": "Saúde da loja", "url": "/painel/saude/", "icon": "fas fa-heart-pulse"},
        {"name": "Ver site", "url": "/", "new_window": True},
    ],
    "icons": {
        "loja.Produto": "fas fa-gem",
        "loja.Pedido": "fas fa-shopping-bag",
        "loja.Carrinho": "fas fa-cart-shopping",
        "loja.ItemCarrinho": "fas fa-box",
        "auth.User": "fas fa-user",
        "loja.Categoria": "fas fa-tags",
    },
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "order_with_respect_to": ["loja"],
}

# Mercado Pago
MERCADOPAGO_ACCESS_TOKEN = os.environ.get('MP_ACCESS_TOKEN')
MERCADOPAGO_PUBLIC_KEY = os.environ.get('MP_PUBLIC_KEY')
MERCADOPAGO_WEBHOOK_SECRET = os.environ.get('MP_WEBHOOK_SECRET', '').strip()
MERCADOPAGO_WEBHOOK_TOLERANCE_SECONDS = int(os.environ.get('MP_WEBHOOK_TOLERANCE_SECONDS', '300'))
MP_TEST_BUYER_EMAIL = os.environ.get('MP_TEST_BUYER_EMAIL', '').strip() or None

class _BotNoiseFilter(logging.Filter):
    """Silencia requisições de bots/scanners em paths conhecidos como ruído."""
    _MUTED_PATHS = frozenset(['/meta.json', '/favicon.ico', '/.env', '/robots.txt'])
    _MUTED_UAS = frozenset([
        'SentryUptimeBot', 'facebookexternalhit', 'meta-externalads', 'Claude-SearchBot',
    ])

    def filter(self, record):
        msg = record.getMessage()
        return not any(x in msg for x in (*self._MUTED_PATHS, *self._MUTED_UAS))


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'bot_noise': {
            '()': 'barrs_store.settings._BotNoiseFilter',
        },
    },
    'formatters': {
        'railway': {
            'format': '[{levelname}] {asctime} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'railway',
            'filters': ['bot_noise'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'loja': {
            'handlers': ['console'],
            'level': os.environ.get('LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        # O Railway inicia o Gunicorn com access log habilitado por fora do
        # gunicorn_config.py, então o desligamento precisa acontecer aqui:
        # o dictConfig do Django roda dentro do worker e remove os handlers
        # do gunicorn.access, silenciando o access log por completo.
        'gunicorn.access': {
            'handlers': [],
            'level': 'CRITICAL',
            'propagate': False,
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

