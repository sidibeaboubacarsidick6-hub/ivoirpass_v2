"""
IvoirPass V2 — Configuration Celery
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('ivoirpass')

# Charger la configuration depuis settings.py (préfixe CELERY_)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-découverte des tâches dans toutes les apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Tâche de debug — vérifie que Celery fonctionne."""
    print(f'Request: {self.request!r}')
