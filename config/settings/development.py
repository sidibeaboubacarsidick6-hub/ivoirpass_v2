"""
IvoirPass V2 - Settings de développement local
"""
from .base import *

# Mode debug activé
DEBUG = True

# Tous les hôtes autorisés en dev
# Autorise toutes les origines ngrok
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '.ngrok-free.dev', 'prepod.ivoirpass.com']

CSRF_TRUSTED_ORIGINS = [
    "https://revengeless-unfervent-deandrea.ngrok-free.dev" ,
    "https://*.ngrok-free.dev",
    "https://prepod.ivoirpass.com",
]

# CORS - uniquement les origines autorisées (dev local + ngrok)
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://revengeless-unfervent-deandrea.ngrok-free.dev",
    "https://*.ngrok-free.dev",
]

CORS_ALLOW_ALL_ORIGINS = False

# Désactivé pour ngrok en développement — sera activé en production
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
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
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=f'IvoirPass <{EMAIL_HOST_USER}>')

# ============================================

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
