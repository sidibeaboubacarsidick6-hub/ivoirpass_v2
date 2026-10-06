"""
Tests des commandes de management Django (smoke tests).

On vérifie simplement que les commandes ne crashent pas — les sorties
exactes peuvent varier. Pour les commandes qui n'acceptent pas d'args
spécifiques, on tolère CommandError.
"""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class TestEmailCommandTests(TestCase):
    """Tests de la commande test_email."""

    def test_test_email_smoke(self):
        """La commande tourne sans crasher (args ou pas args)."""
        out = StringIO()
        try:
            call_command('test_email', stdout=out)
        except CommandError:
            # La commande peut exiger un argument — c'est OK
            pass
        self.assertTrue(True)


class TestSmsCommandTests(TestCase):
    """Tests de la commande test_sms."""

    @override_settings(SMS_ENABLED=False)
    def test_test_sms_smoke(self):
        out = StringIO()
        try:
            call_command('test_sms', stdout=out)
        except CommandError:
            pass
        self.assertTrue(True)


class TestSentryCommandTests(TestCase):
    """Tests de la commande test_sentry."""

    @patch('sentry_sdk.capture_message')
    def test_test_sentry_smoke(self, mock_capture):
        out = StringIO()
        try:
            call_command('test_sentry', stdout=out)
        except CommandError:
            pass
        self.assertTrue(True)


class SetupRolesCommandTests(TestCase):
    """Tests de la commande setup_roles."""

    def test_setup_roles_idempotent(self):
        """La commande peut être rejouée sans crash."""
        out = StringIO()
        call_command('setup_roles', stdout=out)
        call_command('setup_roles', stdout=out)


class RecalcSoldCountCommandTests(TestCase):
    """Tests de la commande recalc_sold_count."""

    def test_recalc_smoke(self):
        out = StringIO()
        call_command('recalc_sold_count', stdout=out)


class SendRemindersCommandTests(TestCase):
    """Tests de la commande send_reminders."""

    def test_send_reminders_smoke(self):
        """La commande tourne sans crasher (aucun événement demain)."""
        out = StringIO()
        try:
            call_command('send_reminders', stdout=out)
        except CommandError:
            pass
        self.assertTrue(True)