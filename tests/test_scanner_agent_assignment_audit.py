"""
Test d'audit — Assignation agent scanner ↔ événement (point du rapport
d'audit : un agent scanner pouvait scanner n'importe quel événement
publié sur la plateforme, faute d'assignation).

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scanner_agent_assignment_audit -v 2
"""
import json
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category


class ScannerAgentAssignmentTests(TestCase):

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-assign@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True,
        )
        self.agent_assigned = CustomUser.objects.create_user(
            email='agent-assigne@test.com', password='Pass123!', role='scanner',
        )
        self.agent_not_assigned = CustomUser.objects.create_user(
            email='agent-non-assigne@test.com', password='Pass123!', role='scanner',
        )
        category = Category.objects.create(name='Concert Assign', slug='concert-assign')
        self.event = Event.objects.create(
            title='Concert Assignation', description='Test', category=category,
            organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        self.event.scanner_agents.add(self.agent_assigned)

    def test_organisateur_peut_assigner_un_agent(self):
        client = Client()
        client.force_login(self.organizer)
        response = client.post(
            reverse('events:assign_scanner_agents', kwargs={'slug': self.event.slug}),
            {'agents': [self.agent_not_assigned.id]},
        )
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertIn(self.agent_not_assigned, self.event.scanner_agents.all())

    def test_agent_assigne_peut_acceder_a_lecran_de_scan_web(self):
        client = Client()
        client.force_login(self.agent_assigned)
        response = client.get(reverse('scanner:scan_event', kwargs={'event_id': self.event.id}))
        self.assertEqual(response.status_code, 200)

    def test_agent_non_assigne_ne_peut_pas_acceder_a_lecran_de_scan_web(self):
        client = Client()
        client.force_login(self.agent_not_assigned)
        response = client.get(reverse('scanner:scan_event', kwargs={'event_id': self.event.id}))
        self.assertEqual(response.status_code, 404)

    def test_agent_non_assigne_absent_de_scanner_index(self):
        client = Client()
        client.force_login(self.agent_not_assigned)
        response = client.get(reverse('scanner:index'))
        all_events = list(response.context['ongoing']) + list(response.context['upcoming']) + list(response.context['past'])
        self.assertNotIn(self.event, all_events)

    def test_agent_assigne_present_dans_scanner_index(self):
        client = Client()
        client.force_login(self.agent_assigned)
        response = client.get(reverse('scanner:index'))
        all_events = list(response.context['ongoing']) + list(response.context['upcoming']) + list(response.context['past'])
        self.assertIn(self.event, all_events)

    def test_api_pwa_refuse_agent_non_assigne(self):
        client = Client()
        client.force_login(self.agent_not_assigned)
        response = client.post(
            reverse('scanner_api:scan_qr'),
            data=json.dumps({'qr_data': 'x:y:z:w', 'event_id': self.event.id}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn('pas assigné', response.json()['message'])

    def test_organisateur_reste_libre_sur_ses_propres_evenements(self):
        """L'organisateur n'a pas besoin d'assignation explicite pour ses propres événements."""
        client = Client()
        client.force_login(self.organizer)
        response = client.get(reverse('scanner:scan_event', kwargs={'event_id': self.event.id}))
        self.assertEqual(response.status_code, 200)
