from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-(u+i!8va1dl!+cy0)qn-nv7ie^d=(r2tac#mmmw9k&p-&@k3f2')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    'https://web-production-c4971.up.railway.app',
    'https://barrsstore.com.br',
    'https://www.barrsstore.com.br',
]

INSTALLED_APPS = [
    'jazzmin', 
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary',
    'cloudinary_storage',
    'loja',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
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

# Cloudinary — armazenamento de imagens
import cloudinary
import cloudinary.uploader
import cloudinary.api

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dsw5fkmwp'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', '588886952591175'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'pq7sOsziSiKTlia5R-odj2oEPNw'),
)

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get('CLOUDINARY_CLOUD_NAME', 'dsw5fkmwp'),
    'API_KEY': os.environ.get('CLOUDINARY_API_KEY', '588886952591175'),
    'API_SECRET': os.environ.get('CLOUDINARY_API_SECRET', 'pq7sOsziSiKTlia5R-odj2oEPNw'),
}

STORAGES = {
    "default": {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

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
    },
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "order_with_respect_to": ["loja"],
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'