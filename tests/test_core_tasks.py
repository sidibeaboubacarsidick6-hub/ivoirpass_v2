"""
Tests des tâches Celery de l'app core — apps/core/tasks.py

Couvre :
- backup_database : succès, échec subprocess, fichier vide, rétention
- _report_failure : Sentry + logger
"""
import os
import subprocess
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from celery.exceptions import Retry

from apps.core import tasks as core_tasks


class ReportFailureTests(TestCase):
    """Tests du helper _report_failure."""

    @patch('sentry_sdk.capture_message')
    def test_report_failure_sans_exception(self, mock_capture):
        """Sans exc → capture_message appelé."""
        core_tasks._report_failure('Test erreur')
        mock_capture.assert_called_once()

    @patch('sentry_sdk.capture_exception')
    def test_report_failure_avec_exception(self, mock_capture):
        """Avec exc → capture_exception appelé."""
        try:
            raise ValueError('Test')
        except ValueError as e:
            core_tasks._report_failure('Msg', exc=e)
            mock_capture.assert_called_once()

    @patch('builtins.__import__', side_effect=ImportError('No sentry'))
    def test_report_failure_sans_sentry(self, mock_import):
        """Sentry absent → pas de crash."""
        try:
            core_tasks._report_failure('Test sans sentry')
        except ImportError:
            self.fail("Ne doit pas propager l'ImportError")


@override_settings(BACKUP_RETENTION_DAYS=7)
class BackupDatabaseTests(TestCase):
    """Tests de backup_database.

    ⚠️ Celery `self.retry(exc=e)` propage l'exception ORIGINALE quand la
    tâche tourne en mode synchrone (test direct, pas via worker). On capture
    donc soit Retry, soit l'exception sous-jacente.
    """

    @patch('apps.core.tasks.subprocess.run')
    def test_backup_succes(self, mock_run):
        """Succès → fichier créé, rétention appliquée."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat, \
             patch('pathlib.Path.glob', return_value=[]):
            mock_stat.return_value.st_size = 1024

            result = core_tasks.backup_database()

            self.assertIn('ivoirpass_backup_', result)
            self.assertTrue(result.endswith('.sql'))

    @patch('apps.core.tasks.subprocess.run')
    def test_backup_echec_subprocess_retry(self, mock_run):
        """Erreur subprocess → Retry levé (ou CalledProcessError propagée)."""
        err = subprocess.CalledProcessError(
            returncode=1, cmd=['pg_dump'], stderr=b'pg_dump: error'
        )
        mock_run.side_effect = err

        with self.assertRaises((Retry, subprocess.CalledProcessError)):
            core_tasks.backup_database()

    @patch('apps.core.tasks.subprocess.run')
    def test_backup_fichier_vide_retry(self, mock_run):
        """Fichier vide après pg_dump → Retry (ou RuntimeError propagée)."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 0

            with self.assertRaises((Retry, RuntimeError)):
                core_tasks.backup_database()

    @patch('apps.core.tasks.subprocess.run')
    def test_backup_fichier_absent_retry(self, mock_run):
        """Fichier absent après pg_dump → Retry (ou RuntimeError propagée)."""
        mock_run.return_value = MagicMock(returncode=0)

        with patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=False):

            with self.assertRaises((Retry, RuntimeError)):
                core_tasks.backup_database()

    @patch('apps.core.tasks.subprocess.run')
    def test_backup_retention_supprime_vieux(self, mock_run):
        """Les sauvegardes > RETENTION_DAYS sont supprimées."""
        mock_run.return_value = MagicMock(returncode=0)

        old_date = datetime.now() - timedelta(days=30)
        old_filename = f"ivoirpass_backup_{old_date.strftime('%Y%m%d_%H%M%S')}.sql"
        fake_old = MagicMock()
        fake_old.stem = old_filename.replace('.sql', '')
        fake_old.unlink = MagicMock()

        recent_date = datetime.now() - timedelta(days=1)
        recent_filename = f"ivoirpass_backup_{recent_date.strftime('%Y%m%d_%H%M%S')}.sql"
        fake_recent = MagicMock()
        fake_recent.stem = recent_filename.replace('.sql', '')
        fake_recent.unlink = MagicMock()

        with patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat, \
             patch('pathlib.Path.glob', return_value=[fake_old, fake_recent]):
            mock_stat.return_value.st_size = 1024

            core_tasks.backup_database()

            fake_old.unlink.assert_called_once()
            fake_recent.unlink.assert_not_called()