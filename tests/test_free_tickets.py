"""
Tests Vague 2.2 — Codes de billets gratuits (2026-09-30).
"""
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event
from apps.tickets.models import FreeTicketCode


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='O', last_name='G',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_event(organizer):
    now = timezone.now()
    return Event.objects.create(
        title='Concert Test',
        slug='concert-test',
        description='Description de test',
        short_description='Concert test',
        organizer=organizer,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=30, hours=3),
        status=Event.Status.PUBLISHED,
    )


class EventFreeTicketsFieldsTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)

    def test_quota_par_defaut_20(self):
        self.assertEqual(self.event.free_tickets_quota, 20)

    def test_compteur_par_defaut_0(self):
        self.assertEqual(self.event.free_tickets_generated, 0)


class FreeTicketCodeModelTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)

    def test_generate_code_format(self):
        code = FreeTicketCode.generate_code()
        self.assertTrue(code.startswith('FREE-'))
        self.assertEqual(len(code), 14)  # FREE-XXXX-XXXX

    def test_generate_code_unique(self):
        """Deux appels ne doivent pas renvoyer le même code."""
        codes = {FreeTicketCode.generate_code() for _ in range(50)}
        self.assertEqual(len(codes), 50)

    def test_generate_code_exclut_confusables(self):
        """Pas de 0/O/1/I/L dans les codes."""
        for _ in range(20):
            code = FreeTicketCode.generate_code()
            body = code.replace('FREE-', '').replace('-', '')
            for c in '01OIL':
                self.assertNotIn(
                    c, body,
                    f"Caractère confusable {c} trouvé dans {code}",
                )

    def test_creation_et_str(self):
        code = FreeTicketCode.objects.create(
            event=self.event,
            code=FreeTicketCode.generate_code(),
            beneficiary_name='Jean Dupont',
            beneficiary_email='jean@test.com',
            created_by=self.org,
        )
        self.assertIn('disponible', str(code))
        self.assertFalse(code.is_used)

    def test_is_used_apres_utilisation(self):
        code = FreeTicketCode.objects.create(
            event=self.event,
            code=FreeTicketCode.generate_code(),
            beneficiary_name='Jean Dupont',
            beneficiary_email='jean@test.com',
            created_by=self.org,
            used_at=timezone.now(),
        )
        self.assertTrue(code.is_used)
        self.assertIn('utilisé', str(code))