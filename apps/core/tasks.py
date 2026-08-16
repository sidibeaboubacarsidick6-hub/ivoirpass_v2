"""
IvoirPass V2 — Tâches Celery de l'app core (sauvegardes, maintenance)
"""
import os
import subprocess
import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


def _report_failure(message, exc=None):
    """Journalise ET remonte à Sentry — une sauvegarde qui échoue
    silencieusement est exactement le genre de panne qu'on ne veut
    découvrir que le jour où on a besoin de restaurer."""
    logger.error(message)
    try:
        import sentry_sdk
        if exc is not None:
            sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_message(message, level='error')
    except ImportError:
        pass


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def backup_database(self):
    """
    Sauvegarde la base de données PostgreSQL et supprime automatiquement
    les sauvegardes de plus de BACKUP_RETENTION_DAYS jours (7 par défaut)
    pour ne pas remplir le disque indéfiniment.

    Appelée automatiquement chaque nuit via CELERY_BEAT_SCHEDULE, et
    reste utilisable manuellement via `python manage.py backup_db`.
    """
    db = settings.DATABASES['default']
    backup_dir = settings.BASE_DIR / 'backups'
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"ivoirpass_backup_{timestamp}.sql"
    filepath = backup_dir / filename

    env = os.environ.copy()
    env['PGPASSWORD'] = db['PASSWORD']

    cmd = [
        'pg_dump',
        '-h', db['HOST'],
        '-p', str(db['PORT']),
        '-U', db['USER'],
        '-d', db['NAME'],
        '-f', str(filepath),
        '--no-owner',
        '--no-acl',
    ]

    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        error_detail = e.stderr.decode() if e.stderr else str(e)
        _report_failure(f"Échec de la sauvegarde de la base de données : {error_detail}")
        raise self.retry(exc=e)

    if not filepath.exists() or filepath.stat().st_size == 0:
        _report_failure(f"Sauvegarde créée mais vide ou absente : {filepath}")
        raise self.retry(exc=RuntimeError("Fichier de sauvegarde vide"))

    logger.info(f"Sauvegarde réussie : {filepath} ({filepath.stat().st_size} octets)")

    # Rétention : supprime les sauvegardes trop anciennes
    retention_days = getattr(settings, 'BACKUP_RETENTION_DAYS', 7)
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for old_file in backup_dir.glob('ivoirpass_backup_*.sql'):
        try:
            file_time = datetime.strptime(old_file.stem.replace('ivoirpass_backup_', ''), '%Y%m%d_%H%M%S')
            if file_time < cutoff:
                old_file.unlink()
                removed += 1
        except (ValueError, OSError) as e:
            logger.warning(f"Impossible de traiter l'ancien fichier {old_file} : {e}")

    if removed:
        logger.info(f"{removed} ancienne(s) sauvegarde(s) supprimée(s) (> {retention_days} jours)")

    return str(filepath)
