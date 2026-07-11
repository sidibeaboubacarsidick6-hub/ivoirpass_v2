"""
Test d'audit — API scanner mobile (authentification JWT par agent, ex-clé
API partagée). Vérifie qu'un agent peut s'authentifier et scanner un billet,
qu'un token invalide/absent est rejeté, et qu'un organisateur ne peut pas
scanner l'événement d'un autre organisateur.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scanner_api_audit -v 2
"""
import json
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem, Ticket
from apps.scanner.models import ScanSession


class ScannerMobileAPITests(TestCase):

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Concerts API', slug='concerts-api')

        self.organizer = CustomUser.objects.create_user(
            email='orga-api@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True,
        )
        self.other_organizer = CustomUser.objects.create_user(
            email='orga-api-2@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True,
        )
        self.scanner_agent = CustomUser.objects.create_user(
            email='agent-api@test.com', password='Pass123!', role='scanner',
        )
        self.buyer = CustomUser.objects.create_user(
            email='buyer-api@test.com', password='Pass123!',
        )

        self.event = Event.objects.create(
            title='Concert API Test', description='Test', category=self.category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event, name='Standard', price=5000, quantity=100,
        )
        self.order = Order.objects.create(buyer=self.buyer, subtotal=5000, total=5000, status='pending')
        OrderItem.objects.create(order=self.order, ticket_type=self.ticket_type, quantity=1, unit_price=5000)
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-API-TEST')
        self.ticket = Ticket.objects.filter(order_item__order=self.order).first()

    def _bearer(self, user):
        token = RefreshToken.for_user(user)
        return f"Bearer {token.access_token}"

    def _qr_data(self):
        return self.ticket.qr_code_data

    def test_scan_sans_token_rejete_401(self):
        response = self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': 'x:y:z:w', 'event_id': self.event.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_scan_avec_token_invalide_rejete(self):
        response = self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': 'x:y:z:w', 'event_id': self.event.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer token-invalide-evidemment',
        )
        self.assertIn(response.status_code, (401, 403))

    def test_agent_scanner_peut_valider_un_vrai_billet(self):
        response = self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': self._qr_data(), 'event_id': self.event.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION=self._bearer(self.scanner_agent),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['result'], 'valid')

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.USED)

        # Traçabilité : le scan doit être attribué au VRAI agent connecté,
        # pas à un compte système partagé.
        session = ScanSession.objects.get(event=self.event, agent=self.scanner_agent)
        self.assertEqual(session.total_valid, 1)

    def test_organisateur_ne_peut_pas_scanner_evenement_dun_autre(self):
        response = self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': self._qr_data(), 'event_id': self.event.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION=self._bearer(self.other_organizer),
        )
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.status, Ticket.Status.USED, "Le billet ne doit pas être marqué utilisé")

    def test_organisateur_peut_scanner_son_propre_evenement(self):
        response = self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': self._qr_data(), 'event_id': self.event.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION=self._bearer(self.organizer),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result'], 'valid')

    def test_utilisateur_sans_role_scanner_rejete(self):
        response = self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': self._qr_data(), 'event_id': self.event.id}),
            content_type='application/json',
            HTTP_AUTHORIZATION=self._bearer(self.buyer),
        )
        self.assertEqual(response.status_code, 403)
