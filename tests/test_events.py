"""
IvoirPass V2 — Tests des événements
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType


class EventModelTest(TestCase):

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email    = 'orga@test.com',
            password = 'IvoirPass2026!',
            role     = 'organizer',
        )
        self.category = Category.objects.create(
            name  = 'concerts',
            slug  = 'concerts',
            icon  = 'bi-music-note',
            color = '#1B7A3E',
        )
        self.now = timezone.now()
        self.event = Event.objects.create(
            title       = 'Festival des Étoiles',
            description = 'Grand festival de musique ivoirienne',
            organizer   = self.organizer,
            category    = self.category,
            start_date  = self.now + timedelta(days=7),
            end_date    = self.now + timedelta(days=7, hours=6),
            venue_city  = 'Abidjan',
            status      = 'published',
        )
        self.ticket_type = TicketType.objects.create(
            event         = self.event,
            name          = 'Standard',
            price         = 5000,
            quantity      = 100,
            max_per_order = 5,
        )

    def test_event_creation(self):
        self.assertEqual(self.event.title, 'Festival des Étoiles')
        self.assertEqual(self.event.status, 'published')
        self.assertEqual(self.event.venue_city, 'Abidjan')

    def test_event_slug_auto_generated(self):
        self.assertIsNotNone(self.event.slug)
        self.assertIn('festival', self.event.slug)

    def test_event_is_upcoming(self):
        self.assertTrue(self.event.is_upcoming)
        self.assertFalse(self.event.is_past)

    def test_ticket_type_remaining(self):
        self.assertEqual(self.ticket_type.remaining, 100)
        self.assertFalse(self.ticket_type.is_sold_out)

    def test_ticket_type_availability(self):
        self.assertTrue(self.ticket_type.is_available)

    def test_event_occupancy_rate_zero(self):
        self.event.total_capacity = 100
        self.event.tickets_sold   = 0
        self.assertEqual(self.event.occupancy_rate, 0)

    def test_event_occupancy_rate_half(self):
        self.event.total_capacity = 100
        self.event.tickets_sold   = 50
        self.assertEqual(self.event.occupancy_rate, 50.0)

    def test_free_event(self):
        self.event.is_free = True
        self.event.save()
        self.assertTrue(self.event.is_free)

    def test_commission_rate_default(self):
        self.assertEqual(float(self.event.commission_rate), 8.0)


class EventViewTest(TestCase):

    def setUp(self):
        self.client    = Client()
        self.organizer = CustomUser.objects.create_user(
            email    = 'orga@test.com',
            password = 'IvoirPass2026!',
            role     = 'organizer',
        )
        self.now   = timezone.now()
        self.event = Event.objects.create(
            title       = 'Concert Test',
            description = 'Description test',
            organizer   = self.organizer,
            start_date  = self.now + timedelta(days=3),
            end_date    = self.now + timedelta(days=3, hours=3),
            venue_city  = 'Abidjan',
            status      = 'published',
        )

    def test_event_list_public(self):
        response = self.client.get(reverse('events:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Concert Test')

    def test_event_detail_public(self):
        response = self.client.get(
            reverse('events:detail', kwargs={'slug': self.event.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Concert Test')

    def test_my_events_requires_login(self):
        response = self.client.get(reverse('events:my_events'))
        self.assertEqual(response.status_code, 302)

    def test_create_event_requires_login(self):
        response = self.client.get(reverse('events:create'))
        self.assertEqual(response.status_code, 302)

    def test_my_events_organizer(self):
        self.client.login(username='orga@test.com', password='IvoirPass2026!')
        response = self.client.get(reverse('events:my_events'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Concert Test')