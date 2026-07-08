"""
IvoirPass V2 - Settings de base
Paramètres communs à tous les environnements
"""
import os
from pathlib import Path
from decouple import config

# ============================================
# CHEMINS DE BASE
# ============================================
BASE_DIR = Path(__file__).resolve().parent.parent.parent

LOGIN_REDIRECT_URL         = '/redirect/'
ACCOUNT_SIGNUP_REDIRECT_URL = '/redirect/'
LOGOUT_REDIRECT_URL         = '/'

# Ferme l'inscription publique — uniquement accessible via lien direct admin si besoin
ACCOUNT_ADAPTER = 'apps.accounts.adapters.NoPublicSignupAdapter'
# ============================================
# SÉCURITÉ
# ============================================
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost').split(',')

# ============================================
# APPLICATIONS INSTALLÉES
# ============================================
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'crispy_forms',
    'crispy_bootstrap5',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

LOCAL_APPS = [
    'apps.accounts',
    'apps.events',
    'apps.tickets',
    'apps.payments',
    'apps.dashboard',
    'apps.scanner',
    'apps.store',
    'apps.notifications',
    'apps.core'
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ============================================
# MIDDLEWARE
# ============================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'csp.middleware.CSPMiddleware',  
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'apps.dashboard.middleware.AuditLogMiddleware',
]

# ============================================
# URLS ET WSGI
# ============================================
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
SITE_ID = 1

# ============================================
# TEMPLATES
# ============================================
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

# ============================================
# BASE DE DONNÉES - PostgreSQL
# ============================================
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='ivoirpass_v2_db'),
        'USER': config('DB_USER', default='ivoirpass_v2_user'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'OPTIONS': {
            'client_encoding': 'UTF8',
        },
    }
}

# ============================================
# AUTHENTIFICATION
# ============================================
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# ============================================
# INTERNATIONALISATION
# ============================================
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Abidjan'
USE_I18N = True
USE_TZ = True

# ============================================
# FICHIERS STATIQUES ET MÉDIAS
# ============================================
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ============================================
# DJANGO REST FRAMEWORK
# ============================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# ============================================
# JWT AUTHENTICATION
# ============================================
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ============================================
# CRISPY FORMS (Bootstrap 5)
# ============================================
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# ============================================
# ALLAUTH — Authentification
# ============================================
ACCOUNT_EMAIL_REQUIRED          = True
ACCOUNT_UNIQUE_EMAIL            = True
ACCOUNT_USERNAME_REQUIRED       = False
ACCOUNT_AUTHENTICATION_METHOD  = 'email'
ACCOUNT_USER_MODEL_USERNAME_FIELD = None


# ✅ Vérification email OBLIGATOIRE
ACCOUNT_EMAIL_VERIFICATION      = 'mandatory'
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION    = True
ACCOUNT_CONFIRM_EMAIL_ON_GET           = True

LOGOUT_REDIRECT_URL = '/'

# Formulaire d'inscription personnalisé
ACCOUNT_FORMS = {
    'signup': 'apps.accounts.forms.IvoirPassSignupForm',
}
# ============================================
# REDIS (Cache)
# ============================================
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# ============================================
# EMAIL
# ============================================
DEFAULT_FROM_EMAIL = 'IvoirPass <noreply@ivoirpass.com>'
EMAIL_SUBJECT_PREFIX = '[IvoirPass] '

# ============================================
# IVOIRPASS - CONFIGURATION MÉTIER
# ============================================
IVOIRPASS = {
    'PLATFORM_NAME': 'IvoirPass',
    'CURRENCY': 'XOF',
    'CURRENCY_SYMBOL': 'FCFA',
    'COMMISSION_TICKETS': 0.08,       # 8% sur billetterie
    'COMMISSION_PHYSICAL': 0.10,      # 10% sur produits physiques
    'COMMISSION_DIGITAL': 0.08,       # 8% sur produits numériques
    'COMMISSION_CAGNOTTE_LOW': 0.02,  # 2% jusqu'à 100 000 FCFA
    'COMMISSION_CAGNOTTE_HIGH': 0.06, # 6% au-delà
    'CAGNOTTE_THRESHOLD': 100000,     # Seuil en FCFA
    'DOWNLOAD_LINK_EXPIRY_HOURS': 48, # Durée de validité des liens de téléchargement
    'CONTACT_EMAIL': 'infos@mks-soft-technologies.com',
    'SUPPORT_PHONE': '+225 07 59 87 21 61',
}

# Clé primaire par défaut
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ============================================
# CELERY — Tâches asynchrones
# ============================================
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Africa/Abidjan'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes max
CELERY_TASK_SOFT_TIME_LIMIT = 60  # 1 minute soft limit


# ============================================
# CELERY BEAT — Tâches planifiées
# ============================================
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'check-pending-withdrawals': {
        'task': 'apps.dashboard.tasks.check_pending_withdrawals',
        'schedule': crontab(hour='8,14,20', minute=0),
    },
    'generate-bceao-report': {
        'task': 'apps.dashboard.tasks.generate_bceao_report',
        'schedule': crontab(hour=8, day_of_month=1),  # 1er de chaque mois à 8h
    },
}

# ============================================
# MODÈLE UTILISATEUR PERSONNALISÉ
# ============================================
AUTH_USER_MODEL = 'accounts.CustomUser'


# ============================================
# PAYDUNYA
# ============================================
PAYDUNYA_MASTER_KEY  = config('PAYDUNYA_MASTER_KEY',  default='')
PAYDUNYA_PRIVATE_KEY = config('PAYDUNYA_PRIVATE_KEY', default='')
PAYDUNYA_TOKEN       = config('PAYDUNYA_TOKEN',        default='')
PAYDUNYA_MODE        = config('PAYDUNYA_MODE',         default='test')
PAYDUNYA_BASE_URL    = config('PAYDUNYA_BASE_URL',     default='http://localhost:8000')

# URL de l'API PayDunya selon le mode
PAYDUNYA_API_BASE = (
    'https://app.paydunya.com/sandbox-api/v1'
    if PAYDUNYA_MODE == 'test'
    else 'https://app.paydunya.com/api/v1'
)

# ============================================
# NOTIFICATIONS
# ============================================
SMS_ENABLED = config('SMS_ENABLED', default=False, cast=bool)

# Orange SMS CI
ORANGE_SMS_CLIENT_ID     = config('ORANGE_SMS_CLIENT_ID',     default='')
ORANGE_SMS_CLIENT_SECRET = config('ORANGE_SMS_CLIENT_SECRET', default='')
ORANGE_SMS_SENDER_NAME   = config('ORANGE_SMS_SENDER_NAME',   default='IvoirPass')

# Twilio
TWILIO_ACCOUNT_SID  = config('TWILIO_ACCOUNT_SID',  default='')
TWILIO_AUTH_TOKEN   = config('TWILIO_AUTH_TOKEN',    default='')
TWILIO_FROM_NUMBER  = config('TWILIO_FROM_NUMBER',   default='')


# ============================================
# CONTENT SECURITY POLICY (CSP)
# ============================================
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    "https://cdn.jsdelivr.net",
    "'unsafe-inline'",
)
CSP_STYLE_SRC = (
    "'self'",
    "https://cdn.jsdelivr.net",
    "https://cdnjs.cloudflare.com",
    "'unsafe-inline'",
)
CSP_IMG_SRC = (
    "'self'",
    "data:",
    "https:",
)
CSP_FONT_SRC = (
    "'self'",
    "https://cdn.jsdelivr.net",
    "https://cdnjs.cloudflare.com",
)
CSP_CONNECT_SRC = (
    "'self'",
    "https://app.paydunya.com",
)
CSP_FRAME_SRC = (
    "'self'",
    "https://app.paydunya.com",
)