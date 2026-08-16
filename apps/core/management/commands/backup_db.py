"""
Commande Django : sauvegarde manuelle de la base de données.
Usage : python manage.py backup_db

Utilise la même logique que la tâche planifiée automatique
(apps.core.tasks.backup_database) — pas de code dupliqué entre
la sauvegarde manuelle et la sauvegarde automatique nocturne.
"""
from django.core.management.base import BaseCommand
from apps.core.tasks import backup_database


class Command(BaseCommand):
    help = 'Sauvegarde la base de données PostgreSQL (manuel, en plus de la sauvegarde nocturne automatique)'

    def handle(self, *args, **options):
        try:
            filepath = backup_database.run()  # exécution synchrone, immédiate
            self.stdout.write(self.style.SUCCESS(f'✅ Backup créé : {filepath}'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'❌ Erreur backup : {e}'))

