from datetime import timedelta
from django.test import TestCase, Client
from django.utils import timezone
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category

class HomeRenderTest(TestCase):
    def test_home_page_avec_evenements_ne_plante_pas(self):
        organizer = CustomUser.objects.create_user(
            email='orga-home@t.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        category = Category.objects.create(name='Concert Home', slug='concert-home')
        Event.objects.create(
            title='LE CONCERTO', description='Test', category=category, organizer=organizer,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        client = Client()
        response = client.get('/')
        print("\nStatus home:", response.status_code)
        self.assertEqual(response.status_code, 200)
