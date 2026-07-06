"""
IvoirPass V2 — Tests du scanner QR Code
"""
import json
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, TicketType
from apps.tickets.models import Order, OrderItem, Ticket
from apps.scanner.models import ScanSession, ScanLog


class QRValidationTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.organizer = CustomUser.objects.create_user(
            email='orga@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        self.participant = CustomUser.objects.create_user(
            email='part@test.com', password='IvoirPass2026!',
            role='participant',
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title='Concert QR Test', description='Test',
            organizer=self.organizer,
            start_date=now + timedelta(hours=2),
            end_date=now + timedelta(hours=6),
            venue_city='Abidjan', status='published',
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event, name='Standard',
            price=5000, quantity=100, max_per_order=5,
        )
        # Crée un billet valide
        order = Order.objects.create(
            buyer=self.participant, subtotal=5000,
            total=5000, status=Order.Status.PENDING,
        )
        item = OrderItem.objects.create(
            order=order, ticket_type=self.ticket_type,
            quantity=1, unit_price=5000,
        )
        order.mark_as_paid(payment_method='test', payment_reference='REF')
        self.ticket = Ticket.objects.get(order_item__order=order)

        # Session de scan
        self.session = ScanSession.objects.create(
            agent=self.organizer,
            event=self.event,
        )

    def test_valid_ticket_scan(self):
        self.client.login(username='orga@test.com', password='IvoirPass2026!')
        response = self.client.post(
            reverse('scanner:validate_qr'),
            data=json.dumps({
                'qr_data':    self.ticket.qr_code_data,
                'event_id':   self.event.id,
                'session_id': self.session.id,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['result'], 'valid')
        self.assertEqual(data['color'],  'green')

    def test_already_used_ticket(self):
        self.ticket.mark_as_used()
        self.client.login(username='orga@test.com', password='IvoirPass2026!')
        response = self.client.post(
            reverse('scanner:validate_qr'),
            data=json.dumps({
                'qr_data':    self.ticket.qr_code_data,
                'event_id':   self.event.id,
                'session_id': self.session.id,
            }),
            content_type='application/json',
        )
        data = json.loads(response.content)
        self.assertEqual(data['result'], 'already_used')
        self.assertEqual(data['color'],  'red')

    def test_invalid_qr_format(self):
        self.client.login(username='orga@test.com', password='IvoirPass2026!')
        response = self.client.post(
            reverse('scanner:validate_qr'),
            data=json.dumps({
                'qr_data':    'invalid-qr-data',
                'event_id':   self.event.id,
                'session_id': self.session.id,
            }),
            content_type='application/json',
        )
        data = json.loads(response.content)
        self.assertEqual(data['result'], 'invalid_qr')

    def test_scan_log_created(self):
        self.client.login(username='orga@test.com', password='IvoirPass2026!')
        self.client.post(
            reverse('scanner:validate_qr'),
            data=json.dumps({
                'qr_data':    self.ticket.qr_code_data,
                'event_id':   self.event.id,
                'session_id': self.session.id,
            }),
            content_type='application/json',
        )
        logs = ScanLog.objects.filter(session=self.session)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().result, 'valid')

    def test_session_counters_updated(self):
        self.client.login(username='orga@test.com', password='IvoirPass2026!')
        self.client.post(
            reverse('scanner:validate_qr'),
            data=json.dumps({
                'qr_data':    self.ticket.qr_code_data,
                'event_id':   self.event.id,
                'session_id': self.session.id,
            }),
            content_type='application/json',
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.total_scanned, 1)
        self.assertEqual(self.session.total_valid,   1)
        self.assertEqual(self.session.total_rejected, 0)