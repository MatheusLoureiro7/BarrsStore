from pathlib import Path
import os
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

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'ALLOWED_HOSTS',
        'barrsstore.com.br,www.barrsstore.com.br,web-production-c4971.up.railway.app,localhost,127.0.0.1'
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

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CSRF_TRUSTED_ORIGINS',
        'https://web-production-c4971.up.railway.app,https://barrsstore.com.br,https://www.barrsstore.com.br'
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
    'loja',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'loja.middleware.BlockScannerPathsMiddleware',
    'loja.middleware.AdminRateLimitMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

# ── SEGURANÇA ──────────────────────────────────────────────────────
if not DEBUG:
    # HTTPS obrigatório
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # Cookies seguros
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = True

    # Proteção HSTS (diz ao browser: só HTTPS por 1 ano)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

    # Proteção XSS e Clickjacking
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False' if DEBUG else 'True') == 'True'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if not DEBUG:
    # Compartilha os cookies entre barrsstore.com.br e www.barrsstore.com.br.
    # Isso evita falha de CSRF quando o cliente navega entre as duas versões do domínio.
    SESSION_COOKIE_DOMAIN = os.environ.get('SESSION_COOKIE_DOMAIN', '.barrsstore.com.br')
    CSRF_COOKIE_DOMAIN = os.environ.get('CSRF_COOKIE_DOMAIN', '.barrsstore.com.br')

# Limitar tentativas de login (proteção brute force)
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend']
ADMIN_RATE_LIMIT = os.environ.get('ADMIN_RATE_LIMIT', '20/5m')

# Sessão expira ao fechar o browser
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 dias

JAZZMIN_SETTINGS = {
    "site_title": "Barrs Store Admin",
    "site_header": "Barrs Store",
    "site_brand": "💎 Barrs Store",
    "welcome_sign": "Bem-vinda ao painel da Barrs Store",
    "copyright": "Barrs Store © 2026",
    "search_model": ["loja.Produto", "loja.Pedido"],
    "topmenu_links": [
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
MERCADOPAGO_WEBHOOK_TOLERANCE_SECONDS = int(os.environ.get('MP_WEBHOOK_TOLERANCE_SECONDS', '600'))
MERCADOPAGO_WEBHOOK_STRICT = (
    os.environ.get('MP_WEBHOOK_STRICT', 'False' if DEBUG else 'True') == 'True'
)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
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
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
