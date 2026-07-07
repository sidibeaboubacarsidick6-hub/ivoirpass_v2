"""
Commande Django : sauvegarde de la base de données
Usage : python manage.py backup_db
"""
import os
import subprocess
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Sauvegarde la base de données PostgreSQL'

    def handle(self, *args, **options):
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
            self.stdout.write(
                self.style.SUCCESS(f'✅ Backup créé : {filepath}')
            )
        except subprocess.CalledProcessError as e:
            self.stderr.write(
                self.style.ERROR(f'❌ Erreur backup : {e.stderr.decode()}')
            )
