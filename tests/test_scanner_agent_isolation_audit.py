"""
Test d'audit — Cloisonnement des agents scanner entre organisateurs.

Contexte : assign_scanner_agents montrait et laissait assigner TOUS les
agents scanner de la plateforme, tous organisateurs confondus — fuite
d'email/nom entre organisateurs sans lien entre eux, et un organisateur
pouvait assigner à son événement l'agent d'un autre organisateur sans son
accord (y compris via un POST forgé contournant le filtre d'affichage).
Corrigé via CustomUser.managed_by + un formulaire self-service de création
d'agent pour l'organisateur.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scanner_agent_isolation_audit -v 2
"""
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category


class ScannerAgentCrossTenantIsolationTests(TestCase):
    def setUp(self):
        self.organizer_a = CustomUser.objects.create_user(
            email='orga-a@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.organizer_b = CustomUser.objects.create_user(
            email='orga-b@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.agent_b = CustomUser.objects.create_user(
            email='agent-de-b@test.com', password='Pass123!', role='scanner', managed_by=self.organizer_b,
        )
        category = Category.objects.create(name='Concert Iso', slug='concert-iso')
        self.event_a = Event.objects.create(
            title='Événement A', description='Test', category=category,
            organizer=self.organizer_a,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )

    def test_organisateur_a_ne_voit_pas_lagent_de_b_dans_la_liste(self):
        client = Client()
        client.force_login(self.organizer_a)
        response = client.get(reverse('events:assign_scanner_agents', kwargs={'slug': self.event_a.slug}))
        self.assertNotContains(response, 'agent-de-b@test.com')

    def test_organisateur_a_ne_peut_pas_assigner_lagent_de_b_meme_en_forcant_le_post(self):
        """Le point le plus important : même en soumettant directement l'ID
        de l'agent de B (en contournant l'interface), l'assignation doit être refusée."""
        client = Client()
        client.force_login(self.organizer_a)
        client.post(
            reverse('events:assign_scanner_agents', kwargs={'slug': self.event_a.slug}),
            {'agents': [self.agent_b.id]},
        )
        self.event_a.refresh_from_db()
        self.assertNotIn(self.agent_b, self.event_a.scanner_agents.all())

    def test_agent_deja_assigne_avant_le_correctif_reste_visible_pour_son_evenement(self):
        """Compatibilité arrière : un agent historique (managed_by=None) déjà
        assigné à un événement ne doit pas disparaître silencieusement de la liste."""
        legacy_agent = CustomUser.objects.create_user(
            email='agent-historique@test.com', password='Pass123!', role='scanner',
        )
        self.event_a.scanner_agents.add(legacy_agent)

        client = Client()
        client.force_login(self.organizer_a)
        response = client.get(reverse('events:assign_scanner_agents', kwargs={'slug': self.event_a.slug}))
        self.assertContains(response, 'agent-historique@test.com')


class CreateScannerAgentSelfServiceTests(TestCase):
    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-create@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.client_ = Client()
        self.client_.login(email='orga-create@test.com', password='Pass123!')

    def test_creation_agent_le_rattache_a_lorganisateur(self):
        self.client_.post(reverse('events:create_scanner_agent'), {
            'email': 'nouvel-agent@test.com', 'first_name': 'Nouvel', 'last_name': 'Agent',
            'password': 'UnMotDePasseSolide123!',
        })
        agent = CustomUser.objects.get(email='nouvel-agent@test.com')
        self.assertEqual(agent.role, CustomUser.Role.SCANNER)
        self.assertEqual(agent.managed_by, self.organizer)

    def test_agent_cree_peut_se_connecter_immediatement(self):
        """L'email doit être vérifié d'emblée — sinon on retombe dans le bug déjà corrigé."""
        self.client_.post(reverse('events:create_scanner_agent'), {
            'email': 'agent-connexion@test.com', 'first_name': 'A', 'last_name': 'B',
            'password': 'UnMotDePasseSolide123!',
        })
        c = Client()
        response = c.post('/accounts/login/', {'login': 'agent-connexion@test.com', 'password': 'UnMotDePasseSolide123!'})
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_email_deja_utilise_est_refuse(self):
        CustomUser.objects.create_user(email='deja-pris@test.com', password='Pass123!', role='scanner')
        response = self.client_.post(reverse('events:create_scanner_agent'), {
            'email': 'deja-pris@test.com', 'password': 'UnMotDePasseSolide123!',
        }, follow=True)
        self.assertEqual(CustomUser.objects.filter(email='deja-pris@test.com').count(), 1)
