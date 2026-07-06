"""
IvoirPass V2 — Tests de la billetterie
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, TicketType
from apps.tickets.models import Order, OrderItem, Ticket


class TicketModelTest(TestCase):

    def setUp(self):
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
            title      = 'Soirée Test',
            description= 'Test',
            organizer  = self.organizer,
            start_date = now + timedelta(days=5),
            end_date   = now + timedelta(days=5, hours=4),
            venue_city = 'Abidjan',
            status     = 'published',
        )
        self.ticket_type = TicketType.objects.create(
            event         = self.event,
            name          = 'VIP',
            price         = 15000,
            quantity      = 50,
            max_per_order = 3,
        )

    def test_order_creation(self):
        order = Order.objects.create(
            buyer    = self.participant,
            subtotal = 15000,
            total    = 15000,
            status   = Order.Status.PENDING,
        )
        self.assertIsNotNone(order.order_number)
        self.assertTrue(order.order_number.startswith('IP-'))

    def test_ticket_generation_after_payment(self):
        order = Order.objects.create(
            buyer    = self.participant,
            subtotal = 15000,
            total    = 15000,
            status   = Order.Status.PENDING,
        )
        item = OrderItem.objects.create(
            order       = order,
            ticket_type = self.ticket_type,
            quantity    = 2,
            unit_price  = 15000,
        )
        order.mark_as_paid(
            payment_method    = 'wave',
            payment_reference = 'TEST-REF-001',
        )
        tickets = Ticket.objects.filter(order_item__order=order)
        self.assertEqual(tickets.count(), 2)

    def test_ticket_number_unique(self):
        order = Order.objects.create(
            buyer=self.participant, subtotal=15000,
            total=15000, status=Order.Status.PENDING,
        )
        item = OrderItem.objects.create(
            order=order, ticket_type=self.ticket_type,
            quantity=2, unit_price=15000,
        )
        order.mark_as_paid(payment_method='test', payment_reference='REF')
        tickets = list(Ticket.objects.filter(order_item__order=order))
        self.assertNotEqual(
            tickets[0].ticket_number,
            tickets[1].ticket_number
        )

    def test_ticket_qr_code_generated(self):
        order = Order.objects.create(
            buyer=self.participant, subtotal=5000,
            total=5000, status=Order.Status.PENDING,
        )
        item = OrderItem.objects.create(
            order=order, ticket_type=self.ticket_type,
            quantity=1, unit_price=5000,
        )
        order.mark_as_paid(payment_method='test', payment_reference='REF2')
        ticket = Ticket.objects.get(order_item__order=order)
        self.assertIsNotNone(ticket.qr_code_data)
        self.assertIn(':', ticket.qr_code_data)

    def test_ticket_mark_as_used(self):
        order = Order.objects.create(
            buyer=self.participant, subtotal=5000,
            total=5000, status=Order.Status.PENDING,
        )
        item = OrderItem.objects.create(
            order=order, ticket_type=self.ticket_type,
            quantity=1, unit_price=5000,
        )
        order.mark_as_paid(payment_method='test', payment_reference='REF3')
        ticket = Ticket.objects.get(order_item__order=order)
        self.assertEqual(ticket.status, 'valid')
        ticket.mark_as_used()
        self.assertEqual(ticket.status, 'used')
        self.assertIsNotNone(ticket.scanned_at)

    def test_free_event_direct_confirmation(self):
        """Un événement gratuit génère les tickets sans paiement."""
        free_ticket_type = TicketType.objects.create(
            event         = self.event,
            name          = 'Gratuit',
            price         = 0,
            quantity      = 200,
            max_per_order = 5,
        )
        order = Order.objects.create(
            buyer=self.participant, subtotal=0,
            total=0, status=Order.Status.PENDING,
        )
        item = OrderItem.objects.create(
            order=order, ticket_type=free_ticket_type,
            quantity=1, unit_price=0,
        )
        order.mark_as_paid(
            payment_method    = 'free',
            payment_reference = f'FREE-{order.order_number}',
        )
        self.assertEqual(order.status, 'paid')
        tickets = Ticket.objects.filter(order_item__order=order)
        self.assertEqual(tickets.count(), 1)


class CartViewTest(TestCase):

    def setUp(self):
        self.client      = Client()
        self.participant = CustomUser.objects.create_user(
            email='part@test.com', password='IvoirPass2026!',
            role='participant',
        )
        self.organizer = CustomUser.objects.create_user(
            email='orga@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title='Event Test', description='desc',
            organizer=self.organizer,
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=2, hours=3),
            venue_city='Abidjan', status='published',
            published_at=now,
            sale_end=now + timedelta(days=1),
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event, name='Standard',
            price=5000, quantity=100, max_per_order=5,
        )

    def test_cart_empty(self):
        response = self.client.get(reverse('tickets:cart'))
        self.assertEqual(response.status_code, 200)

    def test_checkout_requires_login(self):
        response = self.client.get(reverse('tickets:checkout'))
        self.assertEqual(response.status_code, 302)