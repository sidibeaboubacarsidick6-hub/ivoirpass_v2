import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.conf import settings
from apps.core.tasks import backup_database

class BackupRetentionTest(TestCase):
    @override_settings(BACKUP_RETENTION_DAYS=7)
    @patch('apps.core.tasks.subprocess.run')
    def test_retention_supprime_les_vieilles_sauvegardes(self, mock_run):
        backup_dir = settings.BASE_DIR / 'backups'
        backup_dir.mkdir(exist_ok=True)

        # Une sauvegarde vieille de 10 jours (doit être supprimée)
        old_date = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d_%H%M%S')
        old_file = backup_dir / f'ivoirpass_backup_{old_date}.sql'
        old_file.write_text('dummy old backup')

        # Une sauvegarde récente (doit rester)
        recent_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d_%H%M%S')
        recent_file = backup_dir / f'ivoirpass_backup_{recent_date}.sql'
        recent_file.write_text('dummy recent backup')

        # Simule pg_dump réussi : crée un fichier non-vide au bon nom
        def fake_pg_dump(cmd, env, check, capture_output):
            output_path = cmd[cmd.index('-f') + 1]
            with open(output_path, 'w') as f:
                f.write('fake sql dump content')
            return MagicMock()
        mock_run.side_effect = fake_pg_dump

        result_path = backup_database.run()

        print("\nNouveau backup créé:", result_path)
        print("Vieux fichier existe encore?", old_file.exists())
        print("Fichier récent existe encore?", recent_file.exists())

        self.assertFalse(old_file.exists(), "Le vieux backup (10 jours) aurait dû être supprimé")
        self.assertTrue(recent_file.exists(), "Le backup récent (1 jour) ne doit pas être supprimé")

        # Nettoyage
        for f in backup_dir.glob('ivoirpass_backup_*.sql'):
            f.unlink()
