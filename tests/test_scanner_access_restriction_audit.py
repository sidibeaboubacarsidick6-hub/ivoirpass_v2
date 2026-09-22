"""
Test d'audit — Rechargement post-connexion de l'app scanner (jeton CSRF
régénéré par Django à la connexion) et cloisonnement des comptes agent
scanner au reste du site.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scanner_access_restriction_audit -v 2
"""
from django.test import TestCase, Client
from django.urls import reverse

from allauth.account.models import EmailAddress
from apps.accounts.models import CustomUser


class ScannerAppInitialScreenTests(TestCase):
    """La vue scanner_app doit afficher l'écran événement directement pour
    un agent déjà connecté (après le rechargement suivant la connexion),
    et l'écran de connexion sinon."""

    def setUp(self):
        self.agent = CustomUser.objects.create_user(
            email='agent.reload@test.com', password='Pass123!', role=CustomUser.Role.SCANNER,
        )
        EmailAddress.objects.create(user=self.agent, email=self.agent.email, primary=True, verified=True)

    def test_visiteur_non_connecte_voit_lecran_de_connexion(self):
        response = Client().get(reverse('scanner:app'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="loginScreen" class="screen active"')

    def test_agent_connecte_voit_directement_lecran_evenement(self):
        c = Client()
        c.login(email='agent.reload@test.com', password='Pass123!')
        response = c.get(reverse('scanner:app'))
        self.assertContains(response, 'id="eventScreen" class="screen active"')
        self.assertContains(response, self.agent.email)


class ScannerAccessRestrictionTests(TestCase):
    """Un agent scanner ne doit accéder qu'à l'app scanner et son API —
    toute autre page du site le redirige vers l'app scanner."""

    def setUp(self):
        self.agent = CustomUser.objects.create_user(
            email='agent.restrict@test.com', password='Pass123!', role=CustomUser.Role.SCANNER,
        )
        EmailAddress.objects.create(user=self.agent, email=self.agent.email, primary=True, verified=True)
        self.client_ = Client()
        self.client_.login(email='agent.restrict@test.com', password='Pass123!')

    def test_agent_redirige_hors_de_la_page_daccueil(self):
        response = self.client_.get('/', follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('scanner:app'))

    def test_agent_redirige_hors_du_dashboard(self):
        response = self.client_.get('/dashboard/', follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('scanner:app'))

    def test_agent_garde_acces_a_lapp_scanner(self):
        response = self.client_.get(reverse('scanner:app'))
        self.assertEqual(response.status_code, 200)

    def test_agent_garde_acces_a_lapi_scanner(self):
        response = self.client_.post(
            reverse('scanner_api:check_event'), data='{"event_id": 1}',
            content_type='application/json',
        )
        self.assertNotEqual(response.status_code, 302, "L'API scanner ne doit jamais être redirigée")

    def test_organisateur_nest_pas_restreint(self):
        organizer = CustomUser.objects.create_user(
            email='orga.norestrict@test.com', password='Pass123!',
            role=CustomUser.Role.ORGANIZER, is_organizer_verified=True,
        )
        c = Client()
        c.login(email='orga.norestrict@test.com', password='Pass123!')
        response = c.get('/dashboard/', follow=False)
        self.assertNotEqual(response.status_code, 302)

    def test_visiteur_non_connecte_nest_pas_affecte(self):
        response = Client().get('/', follow=False)
        self.assertNotEqual(
            response.url if response.status_code == 302 else None,
            reverse('scanner:app'),
        )
