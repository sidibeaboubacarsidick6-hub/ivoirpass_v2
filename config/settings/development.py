"""
IvoirPass V2 - Settings de développement local
"""
from .base import *

# Mode debug activé
DEBUG = True

# Tous les hôtes autorisés en dev
# Autorise toutes les origines ngrok
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*', '.ngrok-free.dev']

CSRF_TRUSTED_ORIGINS = [
    "https://revengeless-unfervent-deandrea.ngrok-free.dev" ,
    "https://*.ngrok-free.dev",
]

CORS_ALLOWED_ORIGINS = [
    "https://revengeless-unfervent-deandrea.ngrok-free.dev",
    "https://*.ngrok-free.dev",
]

CORS_ALLOW_ALL_ORIGINS = True
SECURE_SSL_REDIRECT = False  # Pour ngrok
SESSION_COOKIE_SECURE = False  # Pour ngrok
CSRF_COOKIE_SECURE = False  # Pour ngrok
# Base de données locale
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='ivoirpass_db'),
        'USER': config('DB_USER', default='ivoirpass_user'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# EMAIL — Console (développement rapide)
# ============================================
#EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# ============================================
# EMAIL — Gmail SMTP
# ============================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST          = 'smtp.gmail.com'
EMAIL_PORT          = 587
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = config('EMAIL_HOST_USER',     default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = f'IvoirPass <{config("EMAIL_HOST_USER", default="")}>'

# ============================================
# CORS - autorise toutes les origines en développement
CORS_ALLOW_ALL_ORIGINS = True

# Debug Toolbar (optionnel - désactivé pour rester simple)
# INSTALLED_APPS += ['debug_toolbar']

# Logs plus verbeux en développement
LOGIN_URL = '/accounts/login/'  
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'apps.store': {
            'handlers':  ['console'],
            'level':     'DEBUG',
            'propagate': False,
        },
    },
}