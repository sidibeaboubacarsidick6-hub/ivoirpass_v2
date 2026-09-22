"""
Test d'audit — Anomalies trouvées lors de la revue de la logique d'envoi
d'emails (avant mise en production) :
- Email de certification organisateur contenait un lien http://127.0.0.1:8000/
  en dur au lieu de l'URL réelle du site.
- apps/store/utils.py:send_download_link_email contenait une URL ngrok
  personnelle en dur (sans impact utilisateur réel, ce chemin n'étant
  jamais atteint pour les commandes invité — mais corrigé par sécurité).

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_email_urls_audit -v 2
"""
from django.core import mail
from django.test import TestCase, override_settings

from apps.accounts.models import CustomUser


@override_settings(PAYDUNYA_BASE_URL='https://prepod.ivoirpass.com')
class OrganizerCertificationEmailTests(TestCase):
    """L'envoi se déclenche depuis CustomUserAdmin.save_model() — on
    l'appelle directement (comme le ferait l'admin Django) plutôt que de
    reconstituer tout le formulaire HTTP, plus fiable et tout aussi fidèle
    au vrai déclencheur."""

    def _save_via_admin(self, organizer, is_organizer_verified):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from apps.accounts.admin import CustomUserAdmin

        organizer.is_organizer_verified = is_organizer_verified
        request = RequestFactory().post('/admin/accounts/customuser/')
        request.user = organizer
        admin_instance = CustomUserAdmin(CustomUser, AdminSite())
        admin_instance.save_model(request, organizer, form=None, change=True)

    def test_email_certification_contient_la_vraie_url_pas_localhost(self):
        organizer = CustomUser.objects.create_user(
            email='orga.cert@test.com', password='Pass123!',
            role=CustomUser.Role.ORGANIZER, is_organizer_verified=False,
        )
        mail.outbox = []
        self._save_via_admin(organizer, True)

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn('https://prepod.ivoirpass.com/accounts/login/', body)
        self.assertNotIn('127.0.0.1', body)

    def test_decertification_envoie_aussi_un_email(self):
        organizer = CustomUser.objects.create_user(
            email='orga.decert@test.com', password='Pass123!',
            role=CustomUser.Role.ORGANIZER, is_organizer_verified=True,
        )
        mail.outbox = []
        self._save_via_admin(organizer, False)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('retirée', mail.outbox[0].subject)
