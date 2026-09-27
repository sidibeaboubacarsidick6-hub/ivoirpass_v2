"""
Test d'audit — Connexion scanner avec email non vérifié.

Contexte : les comptes agent scanner sont créés manuellement (admin), sans
jamais cliquer un lien de confirmation d'email — or ACCOUNT_EMAIL_VERIFICATION
= 'mandatory' empêche alors toute création de session à la connexion,
même avec le bon mot de passe. Le JS de connexion de l'app scanner
(templates/scanner_app/index.html) confondait à tort la redirection vers la
page "email non vérifié" avec un succès. Corrigé pour détecter ce cas
explicitement, et une action d'admin a été ajoutée pour vérifier un email en
un clic.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_scanner_email_verification_audit -v 2
"""
from django.test import TestCase, Client
from django.urls import reverse

from allauth.account.models import EmailAddress
from apps.accounts.models import CustomUser


class UnverifiedEmailLoginTests(TestCase):
    def setUp(self):
        self.agent = CustomUser.objects.create_user(
            email='agent-nonverif@test.com', password='Pass123!', role=CustomUser.Role.SCANNER,
        )

    def test_login_avec_email_non_verifie_ne_cree_pas_de_session(self):
        """Reproduit le bug initial : identifiants corrects mais pas de session (email non vérifié)."""
        c = Client()
        response = c.post('/accounts/login/', {'login': 'agent-nonverif@test.com', 'password': 'Pass123!'})
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_api_scanner_apres_login_non_verifie_renvoie_401(self):
        """Confirme le symptôme observé : l'appel API échoue avec 'session expirée'."""
        c = Client()
        c.post('/accounts/login/', {'login': 'agent-nonverif@test.com', 'password': 'Pass123!'})
        response = c.post(
            reverse('scanner_api:scan_qr'), data='{"qr_data": "x", "event_id": 1}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_login_apres_verification_email_cree_bien_une_session(self):
        """Une fois l'email vérifié, la connexion fonctionne normalement."""
        EmailAddress.objects.create(
            user=self.agent, email=self.agent.email, primary=True, verified=True,
        )
        c = Client()
        response = c.post('/accounts/login/', {'login': 'agent-nonverif@test.com', 'password': 'Pass123!'})
        self.assertTrue(response.wsgi_request.user.is_authenticated)


class CheckEventExistsRequiresAuthTests(TestCase):
    """
    check_event_exists n'appelait pas _check_agent() malgré son propre
    commentaire affirmant le contraire — n'importe qui pouvait sonder
    l'existence d'un événement sans être connecté. Corrigé pour rester
    cohérent avec scan_qr_api.
    """

    def test_check_event_sans_authentification_est_refuse(self):
        response = Client().post(
            reverse('scanner_api:check_event'), data='{"event_id": 1}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_check_event_avec_agent_authentifie_fonctionne(self):
        agent = CustomUser.objects.create_user(
            email='agent-verifie@test.com', password='Pass123!', role=CustomUser.Role.SCANNER,
        )
        EmailAddress.objects.create(user=agent, email=agent.email, primary=True, verified=True)
        c = Client()
        c.login(email='agent-verifie@test.com', password='Pass123!')
        response = c.post(
            reverse('scanner_api:check_event'), data='{"event_id": 1}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)


class AdminVerifyEmailActionTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(email='admverif@test.com', password='Pass123!')
        self.admin.role = CustomUser.Role.ADMIN
        self.admin.save()
        self.agent = CustomUser.objects.create_user(
            email='agent-a-verifier@test.com', password='Pass123!', role=CustomUser.Role.SCANNER,
        )
        self.client_ = Client()
        self.client_.login(email='admverif@test.com', password='Pass123!')

    def test_action_verify_email_addresses_marque_lemail_verifie(self):
        self.assertFalse(EmailAddress.objects.filter(user=self.agent, verified=True).exists())

        response = self.client_.post(
            reverse('admin:accounts_customuser_changelist'),
            {'action': 'verify_email_addresses', '_selected_action': [str(self.agent.pk)]},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EmailAddress.objects.filter(user=self.agent, email=self.agent.email, verified=True).exists())

    def test_apres_action_admin_lagent_peut_se_connecter(self):
        self.client_.post(
            reverse('admin:accounts_customuser_changelist'),
            {'action': 'verify_email_addresses', '_selected_action': [str(self.agent.pk)]},
        )
        c = Client()
        response = c.post('/accounts/login/', {'login': 'agent-a-verifier@test.com', 'password': 'Pass123!'})
        self.assertTrue(response.wsgi_request.user.is_authenticated)
