"""
Test du rapport hebdomadaire (génération Excel + ZIP chiffré + envoi email).
"""
import io
import pyzipper
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.dashboard.reports import build_weekly_report_xlsx, build_weekly_report_zip
from apps.dashboard.tasks import send_weekly_report
from apps.tickets.models import Order


User = get_user_model()


class WeeklyReportTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email='report-test@example.com',
            password='test-1234-report',
            first_name='Test', last_name='Report',
        )
        # Une commande payée récente
        self.order = Order.objects.create(
            buyer=self.user,
            total=Decimal('5000'),
            status=Order.Status.PAID,
            paid_at=timezone.now() - timedelta(days=2),
            payment_method='paydunya',
        )

    # ------------------------------------------------------------------
    # 1. Génération Excel
    # ------------------------------------------------------------------
    def test_build_xlsx_returns_bytes(self):
        xlsx_bytes, week_range = build_weekly_report_xlsx()
        self.assertIsInstance(xlsx_bytes, bytes)
        self.assertGreater(len(xlsx_bytes), 1000)
        self.assertEqual(len(week_range), 2)

    # ------------------------------------------------------------------
    # 2. Génération ZIP chiffré
    # ------------------------------------------------------------------
    @override_settings(WEEKLY_REPORT_ZIP_PASSWORD='motdepasse-test')
    def test_build_zip_returns_encrypted_zip(self):
        zip_bytes, zip_name, week_range = build_weekly_report_zip()
        self.assertIsInstance(zip_bytes, bytes)
        self.assertTrue(zip_name.endswith('.zip'))

        # Le ZIP doit être lisible avec le mot de passe
        buffer = io.BytesIO(zip_bytes)
        with pyzipper.AESZipFile(buffer, 'r') as zf:
            zf.setpassword(b'motdepasse-test')
            names = zf.namelist()
            self.assertEqual(len(names), 1)
            self.assertTrue(names[0].endswith('.xlsx'))

    # ------------------------------------------------------------------
    # 3. ZIP inaccessible sans mot de passe
    # ------------------------------------------------------------------
    @override_settings(WEEKLY_REPORT_ZIP_PASSWORD='motdepasse-test')
    def test_zip_requires_password(self):
        zip_bytes, _, _ = build_weekly_report_zip()
        buffer = io.BytesIO(zip_bytes)
        with pyzipper.AESZipFile(buffer, 'r') as zf:
            with self.assertRaises(RuntimeError):
                # Sans mot de passe, la lecture doit échouer
                zf.read(zf.namelist()[0])

    # ------------------------------------------------------------------
    # 4. Envoi email avec pièce jointe
    # ------------------------------------------------------------------
    @override_settings(
        WEEKLY_REPORT_RECIPIENTS='dest1@example.com,dest2@example.com',
        WEEKLY_REPORT_ZIP_PASSWORD='motdepasse-test',
    )
    def test_send_weekly_report_sends_email(self):
        mail.outbox = []
        result = send_weekly_report()
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(len(email.to), 2)
        self.assertIn('dest1@example.com', email.to)
        self.assertIn('dest2@example.com', email.to)
        self.assertIn('Rapport hebdomadaire', email.subject)
        # 1 pièce jointe (ZIP)
        self.assertEqual(len(email.attachments), 1)
        attachment = email.attachments[0]
        self.assertTrue(attachment[0].endswith('.zip'))
        self.assertEqual(attachment[2], 'application/zip')

    # ------------------------------------------------------------------
    # 5. Sans destinataires → pas d'envoi
    # ------------------------------------------------------------------
    @override_settings(WEEKLY_REPORT_RECIPIENTS='', WEEKLY_REPORT_ZIP_PASSWORD='x')
    def test_no_recipients_no_email(self):
        mail.outbox = []
        result = send_weekly_report()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('Aucun', result)
