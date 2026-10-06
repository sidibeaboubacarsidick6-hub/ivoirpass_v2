"""
Tests du service email — apps/notifications/email_service.py

Couvre :
- send_notification_email : succès + template manquant + pièce jointe
- Injection des variables globales dans le contexte
- Sujet préfixé [IvoirPass]
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class SendNotificationEmailTests(TestCase):
    """Tests de send_notification_email."""

    @patch('apps.notifications.email_service.EmailMultiAlternatives')
    @patch('apps.notifications.email_service.render_to_string')
    def test_email_simple_success(self, mock_render, mock_email_cls):
        """Email envoyé avec HTML + TXT, retourne True."""
        from apps.notifications.email_service import send_notification_email

        mock_render.return_value = 'Contenu du template'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        result = send_notification_email(
            to_email='user@test.com',
            subject='Test envoi',
            template_name='welcome',
            context={'user_name': 'Ali'},
        )

        self.assertTrue(result)
        mock_email.send.assert_called_once_with(fail_silently=False)

        # Vérifie que le sujet a été préfixé
        call_kwargs = mock_email_cls.call_args.kwargs
        self.assertEqual(call_kwargs['subject'], '[IvoirPass] Test envoi')
        self.assertEqual(call_kwargs['to'], ['user@test.com'])

    @patch('apps.notifications.email_service.EmailMultiAlternatives')
    @patch('apps.notifications.email_service.render_to_string')
    def test_email_avec_pieces_jointes(self, mock_render, mock_email_cls):
        """Attachments transmis à l'email."""
        from apps.notifications.email_service import send_notification_email

        mock_render.return_value = 'Contenu'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        attachments = [
            ('facture.pdf', b'contenu-pdf', 'application/pdf'),
            ('billet.pdf', b'contenu-billet', 'application/pdf'),
        ]

        result = send_notification_email(
            to_email='user@test.com',
            subject='Avec pièces',
            template_name='ticket',
            context={},
            attachments=attachments,
        )

        self.assertTrue(result)
        # 2 appels à attach (un par pièce jointe)
        self.assertEqual(mock_email.attach.call_count, 2)

    @patch('apps.notifications.email_service.render_to_string')
    def test_email_template_manquant_retourne_false(self, mock_render):
        """Template plante → retourne False, pas d'exception."""
        from apps.notifications.email_service import send_notification_email

        mock_render.side_effect = Exception('TemplateDoesNotExist')

        result = send_notification_email(
            to_email='user@test.com',
            subject='Test',
            template_name='inexistant',
            context={},
        )

        self.assertFalse(result)

    @patch('apps.notifications.email_service.EmailMultiAlternatives')
    @patch('apps.notifications.email_service.render_to_string')
    def test_context_enrichi_avec_variables_globales(self, mock_render, mock_email_cls):
        """Le contexte reçoit platform_name, year, support_email."""
        from apps.notifications.email_service import send_notification_email

        mock_render.return_value = 'Contenu'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        context = {'user_name': 'Ali'}
        send_notification_email(
            to_email='user@test.com',
            subject='Test',
            template_name='test',
            context=context,
        )

        # Le contexte original a été modifié (update in-place)
        self.assertEqual(context['platform_name'], 'IvoirPass')
        self.assertEqual(context['platform_url'], 'https://test.ivoirpass.com')
        self.assertEqual(context['support_email'], 'infos@mks-soft-technologies.com')
        self.assertIn('year', context)

    @patch('apps.notifications.email_service.EmailMultiAlternatives')
    @patch('apps.notifications.email_service.render_to_string')
    def test_email_smtp_error_retourne_false(self, mock_render, mock_email_cls):
        """Erreur SMTP → retourne False, pas d'exception."""
        from apps.notifications.email_service import send_notification_email

        mock_render.return_value = 'Contenu'
        mock_email = MagicMock()
        mock_email.send.side_effect = Exception('SMTP timeout')
        mock_email_cls.return_value = mock_email

        result = send_notification_email(
            to_email='user@test.com',
            subject='Test',
            template_name='test',
            context={},
        )

        self.assertFalse(result)