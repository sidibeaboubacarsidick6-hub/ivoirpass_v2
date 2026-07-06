"""
IvoirPass V2 — Tests des comptes utilisateurs
"""
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import CustomUser


class CustomUserModelTest(TestCase):

    def setUp(self):
        self.participant = CustomUser.objects.create_user(
            email      = 'participant@test.com',
            password   = 'IvoirPass2026!',
            first_name = 'Kouamé',
            last_name  = 'Diallo',
            role       = 'participant',
        )
        self.organizer = CustomUser.objects.create_user(
            email      = 'organisateur@test.com',
            password   = 'IvoirPass2026!',
            first_name = 'Adjoua',
            last_name  = 'Konan',
            role       = 'organizer',
        )

    def test_user_creation(self):
        self.assertEqual(self.participant.email, 'participant@test.com')
        self.assertEqual(self.participant.role, 'participant')
        self.assertTrue(self.participant.is_active)

    def test_user_roles(self):
        self.assertTrue(self.participant.is_participant)
        self.assertFalse(self.participant.is_organizer)
        self.assertTrue(self.organizer.is_organizer)
        self.assertFalse(self.organizer.is_participant)

    def test_display_name_participant(self):
        self.assertEqual(self.participant.get_full_name(), 'Kouamé Diallo')

    def test_display_name_organizer_no_org(self):
        # Sans organisation → retourne le prénom
        self.assertEqual(self.organizer.get_short_name(), 'Adjoua')

    def test_display_name_organizer_with_org(self):
        self.organizer.organization_name = 'Label Abidjan Music'
        self.organizer.save()
        self.assertEqual(self.organizer.display_name, 'Label Abidjan Music')

    def test_superuser_creation(self):
        admin = CustomUser.objects.create_superuser(
            email    = 'admin@ivoirpass.com',
            password = 'AdminPass2026!',
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertEqual(admin.role, 'admin')


class AccountsViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user   = CustomUser.objects.create_user(
            email    = 'test@test.com',
            password = 'IvoirPass2026!',
            role     = 'participant',
        )

    def test_home_page(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_login_page(self):
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)

    def test_signup_page(self):
        response = self.client.get('/accounts/signup/')
        self.assertEqual(response.status_code, 200)

    def test_profile_requires_login(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)

    def test_profile_accessible_when_logged_in(self):
        self.client.login(
            username='test@test.com',
            password='IvoirPass2026!'
        )
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)