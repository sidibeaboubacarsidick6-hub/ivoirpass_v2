"""
Tests des vues IvoirPass
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem


class HomeViewTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Concerts')
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Festival Accueil',
            description='Description',
            category=self.category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=30),
            end_date=timezone.now() + timedelta(days=31),
            status=Event.Status.PUBLISHED
        )

    def test_home_page_loads(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/home.html')

    def test_home_shows_events(self):
        response = self.client.get(reverse('home'))
        self.assertIn('upcoming_events', response.context)


class EventListViewTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Concerts')
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Concert Public',
            description='Description',
            category=self.category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=14),
            end_date=timezone.now() + timedelta(days=15),
            venue_city='Abidjan',
            status=Event.Status.PUBLISHED
        )

    def test_event_list_loads(self):
        response = self.client.get(reverse('events:list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'events/list.html')

    def test_event_list_shows_published(self):
        response = self.client.get(reverse('events:list'))
        self.assertEqual(response.context['total'], 1)

    def test_event_list_hides_draft(self):
        self.event.status = Event.Status.DRAFT
        self.event.save()
        response = self.client.get(reverse('events:list'))
        self.assertEqual(response.context['total'], 0)


class EventDetailViewTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Concerts')
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Concert Détail',
            description='Description détaillée',
            category=self.category,
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

    def test_event_detail_loads(self):
        response = self.client.get(
            reverse('events:detail', kwargs={'slug': self.event.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'events/detail.html')

    def test_event_detail_shows_ticket_types(self):
        response = self.client.get(
            reverse('events:detail', kwargs={'slug': self.event.slug})
        )
        self.assertEqual(len(response.context['ticket_types']), 1)


class CartViewTest(TestCase):
    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )
        self.event = Event.objects.create(
            title='Événement Panier',
            description='Description',
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=7),
            end_date=timezone.now() + timedelta(days=8),
            status=Event.Status.PUBLISHED
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP',
            price=15000,
            quantity=30
        )

    def test_cart_page_empty(self):
        response = self.client.get(reverse('tickets:cart'))
        self.assertEqual(response.status_code, 200)

    def test_add_to_cart(self):
        response = self.client.post(
            reverse('tickets:add_to_cart', kwargs={'ticket_type_id': self.ticket_type.pk}),
            {'quantity': 2}
        )
        self.assertEqual(response.status_code, 302)
        cart = self.client.session.get('cart', {})
        self.assertIn(str(self.ticket_type.pk), cart)


class AuthViewTest(TestCase):
    def test_signup_page_loads(self):
        response = self.client.get(reverse('account_signup'))
        self.assertEqual(response.status_code, 200)

    def test_login_page_loads(self):
        response = self.client.get(reverse('account_login'))
        self.assertEqual(response.status_code, 200)


class MyTicketsViewTest(TestCase):
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
            title='Événement Billets',
            description='Description',
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=30),
            end_date=timezone.now() + timedelta(days=31),
            status=Event.Status.PUBLISHED
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='Standard',
            price=5000,
            quantity=100
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            subtotal=5000,
            total=5000,
            status=Order.Status.PAID
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            quantity=1,
            unit_price=5000
        )
        self.order_item.generate_tickets()

    def test_my_tickets_requires_login(self):
        response = self.client.get(reverse('tickets:my_tickets'))
        self.assertEqual(response.status_code, 302)

    def test_my_tickets_shows_tickets(self):
        self.client.login(email='buyer@test.com', password='BuyerPass123!')
        response = self.client.get(reverse('tickets:my_tickets'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('upcoming', response.context)
        self.assertEqual(len(response.context['upcoming']), 1)
