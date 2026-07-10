"""
Settings de TEST isolé — ne touche à rien de réel.
- DB : SQLite en mémoire
- Email : backend "locmem" (capturé en mémoire, rien n'est envoyé)
- Celery : exécution synchrone (pas besoin de Redis/worker)
"""
import os
os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('DEBUG', 'True')

from config.settings.base import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES = {
    'default': {
        'BACKEND': 'config.settings.test_cache_shim.ShimCache',
    }
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']  # tests plus rapides

ALLOWED_HOSTS = ['*']
