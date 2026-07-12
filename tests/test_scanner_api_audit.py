"""
Test d'audit — API scanner mobile (authentification JWT par agent + verrou
anti-double-scan pour plusieurs agents simultanés sur le même événement).

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scanner_api_audit -v 2
"""
import json
import threading
from datetime import timedelta

from django.test import TestCase, Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem, Ticket
from apps.scanner.models import ScanSession


def _setup_event_and_ticket(organizer, buyer, suffix=''):
    category = Category.objects.create(name=f'Concerts API{suffix}', slug=f'concerts-api{suffix}')
    event = Event.objects.create(
        title=f'Concert API Test{suffix}', description='Test', category=category,
        organizer=organizer,
        start_date=timezone.now() + timedelta(days=10),
        end_date=timezone.now() + timedelta(days=10, hours=3),
        status='published',
    )
    ticket_type = TicketType.objects.create(event=event, name='Standard', price=5000, quantity=100)
    order = Order.objects.create(buyer=buyer, subtotal=5000, total=5000, status='pending')
    OrderItem.objects.create(order=order, ticket_type=ticket_type, quantity=1, unit_price=5000)
    order.mark_as_paid(payment_method='wave', payment_reference=f'PAY-API-TEST{suffix}')
    ticket = Ticket.objects.filter(order_item__order=order).first()
    return event, ticket


class ScannerMobileAPITests(TestCase):

    def setUp(self):
        self.client = Client()
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
        self.buyer = CustomUser.objects.create_user(email='buyer-api@test.com', password='Pass123!')
        self.event, self.ticket = _setup_event_and_ticket(self.organizer, self.buyer)

    def _bearer(self, user):
        token = RefreshToken.for_user(user)
        return f"Bearer {token.access_token}"

    def _post(self, ticket, event, auth_header=None):
        headers = {}
        if auth_header:
            headers['HTTP_AUTHORIZATION'] = auth_header
        return self.client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': ticket.qr_code_data, 'event_id': event.id}),
            content_type='application/json',
            **headers,
        )

    def test_token_jwt_obtenable_via_api_accounts(self):
        """Le endpoint JWT doit être accessible (il ne l'était pas avant correction)."""
        response = self.client.post(
            '/api/accounts/token/',
            data=json.dumps({'email': 'agent-api@test.com', 'password': 'Pass123!'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.json())

    def test_scan_sans_token_rejete_401(self):
        response = self._post(self.ticket, self.event)
        self.assertEqual(response.status_code, 401)

    def test_scan_avec_token_invalide_rejete(self):
        response = self._post(self.ticket, self.event, auth_header='Bearer invalide')
        self.assertIn(response.status_code, (401, 403))

    def test_agent_scanner_peut_valider_un_vrai_billet(self):
        response = self._post(self.ticket, self.event, auth_header=self._bearer(self.scanner_agent))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result'], 'valid')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.USED)

    def test_le_meme_billet_ne_peut_pas_etre_scanne_deux_fois(self):
        r1 = self._post(self.ticket, self.event, auth_header=self._bearer(self.scanner_agent))
        r2 = self._post(self.ticket, self.event, auth_header=self._bearer(self.scanner_agent))
        self.assertEqual(r1.json()['result'], 'valid')
        self.assertEqual(r2.json()['result'], 'already_used')

    def test_organisateur_ne_peut_pas_scanner_evenement_dun_autre(self):
        response = self._post(self.ticket, self.event, auth_header=self._bearer(self.other_organizer))
        self.assertEqual(response.status_code, 403)
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.status, Ticket.Status.USED)

    def test_utilisateur_sans_role_scanner_rejete(self):
        response = self._post(self.ticket, self.event, auth_header=self._bearer(self.buyer))
        self.assertEqual(response.status_code, 403)


class ScannerConcurrencyTests(TransactionTestCase):
    """
    Plusieurs agents scannant simultanément le même billet — un seul doit
    réussir. TransactionTestCase est nécessaire (pas TestCase) pour que les
    threads voient de vraies transactions séparées, comme en production.
    """

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-concurrent@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True,
        )
        self.agent1 = CustomUser.objects.create_user(email='agent1@test.com', password='Pass123!', role='scanner')
        self.agent2 = CustomUser.objects.create_user(email='agent2@test.com', password='Pass123!', role='scanner')
        self.buyer = CustomUser.objects.create_user(email='buyer-concurrent@test.com', password='Pass123!')
        self.event, self.ticket = _setup_event_and_ticket(self.organizer, self.buyer, suffix='-conc')

    def test_deux_agents_scannent_le_meme_billet_simultanement(self):
        from django.db import connection
        from django.test import skipUnlessDBFeature

        if connection.vendor != 'postgresql':
            self.skipTest(
                "Ce test nécessite Postgres pour un vrai verrouillage de ligne "
                "(select_for_update). SQLite ne gère pas les transactions "
                "concurrentes de la même façon — lancez ce test contre une "
                "vraie base Postgres pour valider la garantie de non-double-scan."
            )

        results = []

        def scan(agent):
            client = Client()
            token = RefreshToken.for_user(agent)
            response = client.post(
                reverse('scanner_api:scan_qr'),
                data=json.dumps({'qr_data': self.ticket.qr_code_data, 'event_id': self.event.id}),
                content_type='application/json',
                HTTP_AUTHORIZATION=f"Bearer {token.access_token}",
            )
            results.append(response.json()['result'])

        t1 = threading.Thread(target=scan, args=(self.agent1,))
        t2 = threading.Thread(target=scan, args=(self.agent2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(
            results.count('valid'), 1,
            f"Un seul scan doit réussir sur deux simultanés, obtenu : {results} "
            f"(note : le verrou select_for_update est pleinement garanti sur "
            f"Postgres en production ; SQLite peut se comporter différemment "
            f"selon la configuration de verrouillage du fichier)."
        )
