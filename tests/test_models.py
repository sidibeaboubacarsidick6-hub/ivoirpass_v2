"""
Tests des modèles IvoirPass
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem, Ticket
from apps.store.models import Product, ProductCategory, ProductOrder, DownloadLink


class CustomUserModelTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Jean',
            last_name='Kouadio'
        )

    def test_create_user(self):
        self.assertEqual(self.user.email, 'test@example.com')
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.role, CustomUser.Role.PARTICIPANT)

    def test_get_full_name(self):
        self.assertEqual(self.user.get_full_name(), 'Jean Kouadio')

    def test_create_organizer(self):
        org = CustomUser.objects.create_user(
            email='org@example.com',
            password='OrgPass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.assertTrue(org.is_organizer)
        self.assertFalse(org.is_organizer_verified)


class EventModelTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name='Concerts',
            icon='bi-music-note-beamed',
            color='#E91E63'
        )
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Festival Test',
            description='Un super festival',
            category=self.category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=7),
            end_date=timezone.now() + timedelta(days=8),
            venue_name='Palais de la Culture',
            venue_city='Abidjan',
            status=Event.Status.PUBLISHED
        )

    def test_event_creation(self):
        self.assertEqual(self.event.title, 'Festival Test')
        self.assertEqual(self.event.slug, 'festival-test')
        self.assertTrue(self.event.is_upcoming)
        self.assertFalse(self.event.is_past)

    def test_event_is_on_sale(self):
        self.assertTrue(self.event.is_on_sale)

    def test_event_absolute_url(self):
        url = self.event.get_absolute_url()
        self.assertIn(self.event.slug, url)


class TicketTypeModelTest(TestCase):
    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Concert Test',
            description='Description',
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=7),
            end_date=timezone.now() + timedelta(days=8),
            status=Event.Status.PUBLISHED
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP',
            price=10000,
            quantity=100,
            max_per_order=5
        )

    def test_ticket_type_creation(self):
        self.assertEqual(self.ticket_type.name, 'VIP')
        self.assertEqual(self.ticket_type.price, 10000)
        self.assertEqual(self.ticket_type.remaining, 100)

    def test_ticket_type_is_available(self):
        self.assertTrue(self.ticket_type.is_available)

    def test_ticket_type_sold_out(self):
        self.ticket_type.quantity = 0
        self.ticket_type.quantity_sold = 0
        self.ticket_type.save()
        self.assertFalse(self.ticket_type.is_sold_out)  # quantity=0 = illimité


class OrderModelTest(TestCase):
    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com',
            password='BuyerPass123!'
        )
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='OrgPass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Événement Test',
            description='Description',
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=7),
            end_date=timezone.now() + timedelta(days=8),
            status=Event.Status.PUBLISHED
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='Standard',
            price=5000,
            quantity=50
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            subtotal=10000,
            total=10000,
            status=Order.Status.PENDING
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            quantity=2,
            unit_price=5000
        )

    def test_order_creation(self):
        self.assertTrue(self.order.order_number.startswith('IP-'))
        self.assertEqual(self.order.status, Order.Status.PENDING)

    def test_order_mark_as_paid(self):
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-123')
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.payment_method, 'wave')
        self.assertIsNotNone(self.order.paid_at)

    def test_order_generates_tickets(self):
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-456')
        tickets = Ticket.objects.filter(order_item__order=self.order)
        self.assertEqual(tickets.count(), 2)

    def test_ticket_qr_code_generation(self):
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-789')
        ticket = Ticket.objects.filter(order_item__order=self.order).first()
        self.assertIsNotNone(ticket.ticket_number)
        self.assertTrue(ticket.ticket_number.startswith('TK-'))
        self.assertTrue(ticket.qr_code_data)

    def test_ticket_verify_qr(self):
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-000')
        ticket = Ticket.objects.filter(order_item__order=self.order).first()
        self.assertTrue(ticket.verify_qr(ticket.qr_code_data))
        self.assertFalse(ticket.verify_qr('faux_qr_data'))

    def test_ticket_mark_as_used(self):
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-111')
        ticket = Ticket.objects.filter(order_item__order=self.order).first()
        ticket.mark_as_used(scanned_by=None)
        self.assertEqual(ticket.status, Ticket.Status.USED)
        self.assertIsNotNone(ticket.scanned_at)


class ProductModelTest(TestCase):
    def setUp(self):
        self.seller = CustomUser.objects.create_user(
            email='seller@test.com',
            password='SellerPass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.product = Product.objects.create(
            name='Livre Test',
            description='Un excellent livre',
            seller=self.seller,
            price=5000,
            product_type=Product.ProductType.PHYSICAL,
            stock=10,
            status=Product.Status.PUBLISHED
        )

    def test_product_creation(self):
        self.assertEqual(self.product.name, 'Livre Test')
        self.assertEqual(self.product.price, 5000)
        self.assertTrue(self.product.is_available)

    def test_product_slug_generation(self):
        self.assertTrue(self.product.slug)
        self.assertIn('livre-test', self.product.slug)

    def test_product_out_of_stock(self):
        self.product.stock = 0
        self.product.save()
        self.assertFalse(self.product.is_available)
