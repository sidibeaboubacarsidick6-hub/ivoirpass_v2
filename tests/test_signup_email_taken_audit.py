"""
Test d'audit — Inscription avec un email déjà utilisé.

Avant ce correctif, s'inscrire avec un email déjà enregistré ne montrait
aucune erreur sur le formulaire : allauth envoyait silencieusement un email
"vous avez déjà un compte" à cette adresse (mesure anti-énumération) et
affichait le même message générique "vérifiez votre boîte mail" que pour
une inscription normale. Corrigé (ACCOUNT_PREVENT_ENUMERATION=False) pour
afficher directement l'erreur sur le formulaire.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_signup_email_taken_audit -v 2
"""
from django.core import mail
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import CustomUser


class SignupEmailAlreadyTakenTests(TestCase):
    def setUp(self):
        self.existing = CustomUser.objects.create_user(
            email='deja.inscrit@test.com', password='Pass123!', role=CustomUser.Role.ORGANIZER,
        )

    def test_inscription_avec_email_existant_affiche_une_erreur(self):
        mail.outbox = []
        response = self.client.post(reverse('account_signup'), {
            'email': 'deja.inscrit@test.com',
            'password1': 'UnMotDePasseSolide123!',
            'password2': 'UnMotDePasseSolide123!',
        })
        self.assertEqual(response.status_code, 200, "Doit rester sur le formulaire avec une erreur, pas rediriger")
        self.assertTrue(response.context['form'].errors, "Le formulaire doit porter une erreur")

    def test_inscription_avec_email_existant_nenvoie_aucun_email(self):
        mail.outbox = []
        self.client.post(reverse('account_signup'), {
            'email': 'deja.inscrit@test.com',
            'password1': 'UnMotDePasseSolide123!',
            'password2': 'UnMotDePasseSolide123!',
        })
        self.assertEqual(len(mail.outbox), 0, "Aucun email ne doit partir vers un compte déjà existant")

    def test_inscription_avec_nouvel_email_fonctionne_normalement(self):
        response = self.client.post(reverse('account_signup'), {
            'email': 'nouveau.compte@test.com',
            'first_name': 'Nouveau', 'last_name': 'Compte', 'role': 'organizer',
            'password1': 'UnMotDePasseSolide123!',
            'password2': 'UnMotDePasseSolide123!',
        })
        self.assertEqual(response.status_code, 302, "Une inscription valide doit rediriger normalement")
        self.assertTrue(CustomUser.objects.filter(email='nouveau.compte@test.com').exists())
