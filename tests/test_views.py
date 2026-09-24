"""
Tests des vues IvoirPass
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType



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


class AuthViewTest(TestCase):
    def test_signup_page_loads(self):
        response = self.client.get(reverse('account_signup'))
        self.assertEqual(response.status_code, 200)

    def test_login_page_loads(self):
        response = self.client.get(reverse('account_login'))
        self.assertEqual(response.status_code, 200)



