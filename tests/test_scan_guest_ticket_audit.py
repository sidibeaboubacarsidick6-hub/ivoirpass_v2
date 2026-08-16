"""
Test d'audit — Le scan (web ET PWA) doit valider aussi les billets
achetés sans compte (GuestTicket), pas seulement les comptes normaux.
Bug remonté par l'équipe : "scan non validé, ticket introuvable" sur
un billet acheté en mode invité (Phase 6 et Phase 10 du script MVP).

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scan_guest_ticket_audit -v 2
"""
import json
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import GuestOrder, GuestOrderItem, GuestTicket
from apps.scanner.models import ScanSession


class ScanGuestTicketWebTests(TestCase):
    """Le scanner web (utilisé dans le navigateur) doit accepter les billets invités."""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-guestscan@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True,
        )
        self.agent = CustomUser.objects.create_user(
            email='agent-guestscan@test.com', password='Pass123!', role='scanner',
        )
        category = Category.objects.create(name='Concert Guest Scan', slug='concert-guest-scan')
        self.event = Event.objects.create(
            title='Concert Invité', description='Test', category=category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        self.ticket_type = TicketType.objects.create(event=self.event, name='Standard', price=5000, quantity=100)

        order = GuestOrder.objects.create(
            first_name='Jean', last_name='Kouadio', email='jean@test.com',
            subtotal=5000, total=5000, status='pending'
        )
        item = GuestOrderItem.objects.create(
            order=order, ticket_type=self.ticket_type, quantity=1, unit_price=5000
        )
        order.mark_as_paid(payment_method='orange_money', payment_reference='PAY-GUEST-SCAN')
        self.guest_ticket = item.tickets.first()

    def test_scanner_web_valide_un_billet_invite(self):
        client = Client()
        client.force_login(self.agent)
        session = ScanSession.objects.create(event=self.event, agent=self.agent)

        response = client.post(
            reverse('scanner:validate_qr'),
            data=json.dumps({
                'qr_data': self.guest_ticket.qr_code_data,
                'event_id': self.event.id,
                'session_id': session.id,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['result'], 'valid', f"Résultat inattendu : {payload}")

        self.guest_ticket.refresh_from_db()
        self.assertEqual(self.guest_ticket.status, 'used')

    def test_scanner_web_refuse_le_meme_billet_invite_deux_fois(self):
        client = Client()
        client.force_login(self.agent)
        session = ScanSession.objects.create(event=self.event, agent=self.agent)

        body = json.dumps({
            'qr_data': self.guest_ticket.qr_code_data,
            'event_id': self.event.id,
            'session_id': session.id,
        })
        r1 = client.post(reverse('scanner:validate_qr'), data=body, content_type='application/json')
        r2 = client.post(reverse('scanner:validate_qr'), data=body, content_type='application/json')
        self.assertEqual(r1.json()['result'], 'valid')
        self.assertEqual(r2.json()['result'], 'already_used')


class ScanGuestTicketAPITests(TestCase):
    """L'API scanner (utilisée par la PWA scanner_app) doit aussi accepter les billets invités."""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-guestapi@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True,
        )
        self.agent = CustomUser.objects.create_user(
            email='agent-guestapi@test.com', password='Pass123!', role='scanner',
        )
        category = Category.objects.create(name='Concert Guest API', slug='concert-guest-api')
        self.event = Event.objects.create(
            title='Concert Invité API', description='Test', category=category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        self.ticket_type = TicketType.objects.create(event=self.event, name='Standard', price=5000, quantity=100)
        self.event.scanner_agents.add(self.agent)

        order = GuestOrder.objects.create(
            first_name='Awa', last_name='Traore', email='awa@test.com',
            subtotal=5000, total=5000, status='pending'
        )
        item = GuestOrderItem.objects.create(
            order=order, ticket_type=self.ticket_type, quantity=1, unit_price=5000
        )
        order.mark_as_paid(payment_method='orange_money', payment_reference='PAY-GUEST-API')
        self.guest_ticket = item.tickets.first()

    def test_api_scanner_valide_un_billet_invite(self):
        client = Client()
        client.force_login(self.agent)

        response = client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': self.guest_ticket.qr_code_data, 'event_id': self.event.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['result'], 'valid', f"Résultat inattendu : {payload}")
        self.assertEqual(payload['ticket_info']['buyer_name'], 'Awa Traore')

        self.guest_ticket.refresh_from_db()
        self.assertEqual(self.guest_ticket.status, 'used')