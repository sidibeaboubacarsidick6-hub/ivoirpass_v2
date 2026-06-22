"""
IvoirPass V2 - Settings de développement local
"""
from .base import *

# Mode debug activé
DEBUG = True

# Tous les hôtes autorisés en dev
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

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

# Email affiché dans la console en développement
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS - autorise toutes les origines en développement
CORS_ALLOW_ALL_ORIGINS = True

# Debug Toolbar (optionnel - désactivé pour rester simple)
# INSTALLED_APPS += ['debug_toolbar']

# Logs plus verbeux en développement
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}