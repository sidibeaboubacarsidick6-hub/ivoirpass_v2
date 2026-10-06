"""
Tests des utilitaires boutique — apps/store/utils.py

Couvre :
- send_download_link_email : envoi OK, pas d'email, pas de liens
- Retour silencieux si erreur SMTP
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
)
class SendDownloadLinkEmailTests(TestCase):
    """Tests de send_download_link_email."""

    @patch('apps.store.utils.EmailMultiAlternatives')
    @patch('apps.store.utils.render_to_string')
    def test_email_envoye_si_conditions_ok(self, mock_render, mock_email_cls):
        """Email envoyé si buyer.email + download_links existent."""
        from apps.store.utils import send_download_link_email

        mock_render.return_value = '<html>Liens</html>'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        # Fake order + download_links
        order = MagicMock()
        order.buyer.email = 'buyer@test.com'
        order.product.name = 'Album Test'

        mock_links = MagicMock()
        mock_links.exists.return_value = True
        order.download_links.all.return_value = mock_links

        send_download_link_email(order)

        # Email envoyé
        mock_email.send.assert_called_once_with(fail_silently=True)
        # Sujet contient le nom du produit
        call_kwargs = mock_email_cls.call_args.kwargs
        self.assertIn('Album Test', call_kwargs['subject'])
        self.assertEqual(call_kwargs['to'], ['buyer@test.com'])

    @patch('apps.store.utils.EmailMultiAlternatives')
    def test_pas_demail_si_buyer_email_vide(self, mock_email_cls):
        """Buyer sans email → pas d'envoi."""
        from apps.store.utils import send_download_link_email

        order = MagicMock()
        order.buyer.email = ''  # ← vide

        send_download_link_email(order)

        mock_email_cls.assert_not_called()

    @patch('apps.store.utils.EmailMultiAlternatives')
    def test_pas_demail_si_pas_de_liens(self, mock_email_cls):
        """Aucun download_link → pas d'envoi."""
        from apps.store.utils import send_download_link_email

        order = MagicMock()
        order.buyer.email = 'buyer@test.com'
        mock_links = MagicMock()
        mock_links.exists.return_value = False
        order.download_links.all.return_value = mock_links

        send_download_link_email(order)

        mock_email_cls.assert_not_called()

    @patch('apps.store.utils.EmailMultiAlternatives')
    @patch('apps.store.utils.render_to_string')
    def test_erreur_smtp_avalee(self, mock_render, mock_email_cls):
        """Erreur SMTP → pas d'exception levée (fail_silently)."""
        from apps.store.utils import send_download_link_email

        mock_render.return_value = '<html>Test</html>'
        mock_email = MagicMock()
        mock_email.send.side_effect = Exception('SMTP down')
        mock_email_cls.return_value = mock_email

        order = MagicMock()
        order.buyer.email = 'buyer@test.com'
        order.product.name = 'Test'
        mock_links = MagicMock()
        mock_links.exists.return_value = True
        order.download_links.all.return_value = mock_links

        # Ne doit PAS lever d'exception
        try:
            send_download_link_email(order)
        except Exception as e:
            self.fail(f"send_download_link_email a levé une exception : {e}")