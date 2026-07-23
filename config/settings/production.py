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

LOG_DIR = '/var/log/ivoirpass'

# Crée le dossier de logs s'il n'existe pas (ignore l'erreur si pas de permission)
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except (PermissionError, OSError):
    pass

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

# Ajouter le handler fichier uniquement si le dossier existe
if os.path.exists(LOG_DIR) and os.access(LOG_DIR, os.W_OK):
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

# ============================================
# SENTRY — Alertes en temps réel sur les erreurs
#
# Sans ceci, une erreur qui plante silencieusement (ex: un webhook qui
# échoue, un email qui ne part pas) ne se voit que dans les logs du
# serveur, que personne ne regarde en continu. Avec Sentry, une alerte
# arrive automatiquement (email/Slack) dès qu'une erreur se produit,
# qu'elle soit "fatale" (erreur 500) ou juste attrapée et journalisée
# quelque part dans le code (voir sentry_sdk.capture_exception ajouté
# dans apps/notifications/tasks.py pour les échecs d'email silencieux).
#
# SENTRY_DSN vide (valeur par défaut) = Sentry désactivé, aucun impact
# sur le fonctionnement du site tant que la variable n'est pas définie.
# ============================================
SENTRY_DSN = config('SENTRY_DSN', default='')

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=None, event_level='ERROR'),
        ],
        environment=config('SENTRY_ENVIRONMENT', default='production'),
        # Garde une trace de 100% des erreurs, mais échantillonne les
        # traces de performance pour ne pas surcharger le quota gratuit.
        traces_sample_rate=0.1,
        send_default_pii=False,  # ne jamais envoyer de données personnelles à Sentry
    )