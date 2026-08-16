"""
Commande Django : restauration de la base de données depuis une sauvegarde
créée par backup_db / backup_database.

Usage :
    python manage.py restore_db --list                     (voir les sauvegardes disponibles)
    python manage.py restore_db backups/ivoirpass_backup_20260101_030000.sql
"""
import os
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = 'Restaure la base de données PostgreSQL depuis un fichier de sauvegarde'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file', nargs='?', type=str,
            help="Chemin vers le fichier .sql à restaurer"
        )
        parser.add_argument(
            '--list', action='store_true',
            help="Liste les sauvegardes disponibles dans backups/ sans restaurer"
        )
        parser.add_argument(
            '--yes', action='store_true',
            help="Confirme la restauration sans demander (dangereux — écrase la base actuelle)"
        )

    def handle(self, *args, **options):
        backup_dir = settings.BASE_DIR / 'backups'

        if options['list'] or not options['backup_file']:
            backups = sorted(backup_dir.glob('ivoirpass_backup_*.sql'), reverse=True)
            if not backups:
                self.stdout.write(self.style.WARNING("Aucune sauvegarde trouvée dans backups/"))
                return
            self.stdout.write("Sauvegardes disponibles (les plus récentes en premier) :")
            for b in backups:
                size_mb = b.stat().st_size / (1024 * 1024)
                self.stdout.write(f"  {b}  ({size_mb:.1f} Mo)")
            self.stdout.write("\nPour restaurer : python manage.py restore_db <chemin_du_fichier>")
            return

        filepath = Path(options['backup_file'])
        if not filepath.is_absolute():
            filepath = Path.cwd() / filepath

        if not filepath.exists():
            raise CommandError(f"Fichier introuvable : {filepath}")

        db = settings.DATABASES['default']

        self.stdout.write(self.style.WARNING(
            f"\n⚠️  ATTENTION : ceci va ÉCRASER la base de données actuelle "
            f"'{db['NAME']}' avec le contenu de :\n  {filepath}\n"
        ))

        if not options['yes']:
            confirm = input("Tape exactement 'RESTAURER' pour confirmer, ou Ctrl+C pour annuler : ")
            if confirm != 'RESTAURER':
                self.stdout.write(self.style.ERROR("Annulé — rien n'a été modifié."))
                return

        env = os.environ.copy()
        env['PGPASSWORD'] = db['PASSWORD']

        # Restauration : on vide les tables existantes puis on rejoue le dump.
        # --clean --if-exists sur le dump généré par pg_dump gère la partie
        # suppression ; ici on s'assure juste que psql applique le fichier.
        cmd = [
            'psql',
            '-h', db['HOST'],
            '-p', str(db['PORT']),
            '-U', db['USER'],
            '-d', db['NAME'],
            '-f', str(filepath),
        ]

        self.stdout.write("Restauration en cours...")
        try:
            result = subprocess.run(cmd, env=env, check=True, capture_output=True)
            self.stdout.write(self.style.SUCCESS(f"✅ Restauration terminée depuis {filepath}"))
        except subprocess.CalledProcessError as e:
            error_detail = e.stderr.decode() if e.stderr else str(e)
            raise CommandError(f"Échec de la restauration : {error_detail}")

        self.stdout.write(self.style.WARNING(
            "Pense à relancer 'python manage.py migrate' si la sauvegarde "
            "est plus ancienne que le schéma actuel du code."
        ))
