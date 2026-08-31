"""
IvoirPass V2 - Settings de production (OVH)
"""
import os
from .base import *

# ============================================
# MODE PRODUCTION
# ============================================
DEBUG = False

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='ivoirpass.com').split(',')

# ============================================
# SÉCURITÉ HTTPS
# ============================================
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_HTTPONLY = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'

# ============================================
# CORS
# ============================================
CORS_ALLOWED_ORIGINS = [
    'https://ivoirpass.com',
    'https://www.ivoirpass.com',
]

CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='https://ivoirpass.com,https://www.ivoirpass.com'
).split(',')

# ============================================
# EMAIL SMTP
# ============================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = f'IvoirPass <{config("EMAIL_HOST_USER", default="noreply@ivoirpass.com")}>'

# ============================================
# LOGGING
# ============================================
import os

# Configurable via .env pour s'adapter à l'environnement de déploiement
# (volume Docker monté, chemin serveur classique, etc.) — avec un repli
# garanti dans le projet lui-même si le chemin préféré n'est pas
# accessible, plutôt qu'un échec silencieux qui ferait perdre les logs
# de niveau WARNING sans que personne ne s'en aperçoive.
LOG_DIR = config('LOG_DIR', default='/var/log/ivoirpass')

try:
    os.makedirs(LOG_DIR, exist_ok=True)
    if not os.access(LOG_DIR, os.W_OK):
        raise PermissionError(f"{LOG_DIR} non accessible en écriture")
except (PermissionError, OSError):
    # Repli : dossier logs/ à la racine du projet, toujours accessible
    # à l'utilisateur qui fait tourner l'application.
    LOG_DIR = str(BASE_DIR / 'logs')
    os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': True,
        },
    },
}

# Le handler fichier est toujours actif : LOG_DIR est garanti exister et
# être accessible en écriture à ce stade (voir le bloc plus haut, avec
# son repli automatique vers BASE_DIR/logs en cas d'échec).
LOGGING['handlers']['file'] = {
    'level': 'WARNING',
    'class': 'logging.handlers.RotatingFileHandler',
    'filename': os.path.join(LOG_DIR, 'django.log'),
    'maxBytes': 10 * 1024 * 1024,
    'backupCount': 5,
    'formatter': 'verbose',
}
for logger in LOGGING['loggers'].values():
    logger['handlers'].append('file')

# ============================================
# ADMINS (emails erreurs 500)
# ============================================
ADMINS = [
    ('Admin IvoirPass', config('ADMIN_EMAIL', default='admin@ivoirpass.com')),
]

# ============================================
# RATE LIMITING
# ============================================
RATELIMIT_ENABLE = True
