"""
Tests Vague 2.2 S3 — Réclamation d'un code de billet gratuit (2026-09-30).
"""
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, TicketType
from apps.tickets.models import (
    FreeTicketCode, GuestOrder, GuestTicket,
)


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='O', last_name='G',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_event(organizer, status=None, slug=None):
    if status is None:
        status = Event.Status.PUBLISHED
    if slug is None:
        import uuid as _uuid
        slug = f'concert-test-{_uuid.uuid4().hex[:8]}'
    now = timezone.now()
    return Event.objects.create(
        title='Concert Test',
        slug=slug,
        description='Description',
        short_description='Concert test',
        organizer=organizer,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=30, hours=3),
        status=status,
    )


def _make_ticket_type(event, price=5000):
    return TicketType.objects.create(
        event=event,
        name='Standard',
        price=price,
        quantity=100,
    )


def _make_code(event, ticket_type, code='FREE-TEST-0001'):
    org = event.organizer
    return FreeTicketCode.objects.create(
        event=event,
        ticket_type=ticket_type,
        code=code,
        beneficiary_name='Jean Dupont',
        beneficiary_email='jean@test.com',
        created_by=org,
    )


class ClaimFreeTicketTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)
        self.ticket_type = _make_ticket_type(self.event)
        self.code = _make_code(self.event, self.ticket_type)

    def test_claim_valide_cree_order_et_ticket(self):
        """Code valide → GuestOrder + GuestOrderItem + GuestTicket créés."""
        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': self.code.code},
        )
        # Redirection vers la page de confirmation
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/guest/confirmation/', resp.url)

        # Le code est marqué utilisé
        self.code.refresh_from_db()
        self.assertIsNotNone(self.code.used_at)
        self.assertIsNotNone(self.code.guest_ticket)

        # La commande existe et est gratuite
        order = GuestOrder.objects.get(email='jean@test.com')
        self.assertEqual(order.status, GuestOrder.Status.PAID)
        self.assertEqual(order.total, 0)
        self.assertEqual(order.payment_method, 'free_code')

        # Le billet existe
        self.assertTrue(
            GuestTicket.objects.filter(order_item__order=order).exists()
        )

    def test_claim_code_inexistant_erreur(self):
        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': 'FREE-ZZZZ-ZZZZ'},
        )
        # Reste sur la page (pas de redirection)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Code introuvable')
        self.assertFalse(GuestOrder.objects.exists())

    def test_claim_code_deja_utilise_erreur(self):
        # Marque le code comme utilisé
        self.code.used_at = timezone.now()
        self.code.save()

        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': self.code.code},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'déjà été utilisé')
        self.assertFalse(GuestOrder.objects.exists())

    def test_claim_code_autre_evenement_erreur(self):
        """Un code d'un autre événement ne doit pas fonctionner."""
        other_event = _make_event(self.org, slug='autre-concert')
        other_tt = _make_ticket_type(other_event)
        other_code = _make_code(
            other_event, other_tt, code='FREE-OTHR-9999',
        )

        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': other_code.code},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Code introuvable')

    def test_claim_event_non_publie_404(self):
        """Événement non publié → 404."""
        self.event.status = Event.Status.DRAFT
        self.event.save()

        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': self.code.code},
        )
        self.assertEqual(resp.status_code, 404)

    def test_claim_code_insensible_a_la_casse(self):
        """Le code est uppercasé : free-test-0001 doit marcher."""
        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': self.code.code.lower()},
        )
        self.assertEqual(resp.status_code, 302)

    def test_claim_avec_espaces_autour(self):
        """Les espaces autour sont nettoyés."""
        resp = self.client.post(
            f'/evenements/{self.event.slug}/code-gratuit/',
            {'code': f'  {self.code.code}  '},
        )
        self.assertEqual(resp.status_code, 302)