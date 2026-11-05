"""
Tests du service SMS — apps/notifications/sms.py

Couvre la nouvelle implémentation via l'API Boss (paas-notifications.com) :
- Normalisation des numéros (225XXXXXXXXXX)
- Respect de SMS_ENABLED
- Troncature à 160 caractères
- Gestion des réponses HTTP (200/201/202 → True, autres → False)
- Erreur réseau
- Numéro invalide ou message vide
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from apps.notifications.sms import _format_phone, send_sms


class FormatPhoneTests(TestCase):
    """Tests de la normalisation du numéro."""

    def test_phone_avec_espaces_et_tirets(self):
        self.assertEqual(_format_phone('+225 07 00 00 00 00'), '2250700000000')
        self.assertEqual(_format_phone('+225-07-00-00-00-00'), '2250700000000')

    def test_phone_local_sans_indicatif(self):
        self.assertEqual(_format_phone('0700000000'), '2250700000000')

    def test_phone_avec_prefixe_225(self):
        self.assertEqual(_format_phone('2250700000000'), '2250700000000')

    def test_phone_avec_prefixe_00(self):
        self.assertEqual(_format_phone('002250700000000'), '2250700000000')

    def test_phone_vide_retourne_vide(self):
        self.assertEqual(_format_phone(''), '')
        self.assertEqual(_format_phone(None), '')

    def test_phone_invalide_trop_court(self):
        """Moins de 10 chiffres → rejeté."""
        self.assertEqual(_format_phone('0700'), '')
        self.assertEqual(_format_phone('12345'), '')

    def test_phone_invalide_trop_long(self):
        """Plus de 10 chiffres après le préfixe → rejeté."""
        self.assertEqual(_format_phone('07000000001'), '')


@override_settings(SMS_ENABLED=False)
class SmsDisabledTests(TestCase):
    """Quand SMS_ENABLED=False → pas d'envoi, retourne True (mode dev)."""

    @patch('apps.notifications.sms.requests.post')
    def test_send_sms_desactive(self, mock_post):
        result = send_sms('0700000000', 'Test')
        self.assertTrue(result)
        mock_post.assert_not_called()


@override_settings(
    SMS_ENABLED=True,
    SMS_SENDER_ID='DIGITICKETS',
)
class SmsEnabledTests(TestCase):
    """Quand SMS_ENABLED=True → envoi réel via l'API Boss."""

    @patch('apps.notifications.sms.requests.post')
    def test_envoi_success_200(self, mock_post):
        """HTTP 200 → True."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'OK'
        mock_post.return_value = mock_resp

        result = send_sms('0700000000', 'Test SMS')
        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch('apps.notifications.sms.requests.post')
    def test_envoi_success_201(self, mock_post):
        """HTTP 201 → True."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.text = 'Created'
        mock_post.return_value = mock_resp

        result = send_sms('0700000000', 'Test SMS')
        self.assertTrue(result)

    @patch('apps.notifications.sms.requests.post')
    def test_envoi_echec_403(self, mock_post):
        """HTTP 403 (whitelist) → False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = 'Forbidden'
        mock_post.return_value = mock_resp

        result = send_sms('0700000000', 'Test')
        self.assertFalse(result)

    @patch('apps.notifications.sms.requests.post')
    def test_envoi_echec_500(self, mock_post):
        """HTTP 500 → False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = 'Server Error'
        mock_post.return_value = mock_resp

        result = send_sms('0700000000', 'Test')
        self.assertFalse(result)

    @patch('apps.notifications.sms.requests.post')
    def test_troncature_message_trop_long(self, mock_post):
        """Message > 160 chars → tronqué à 157 + '...'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'OK'
        mock_post.return_value = mock_resp

        long_message = 'A' * 300
        send_sms('0700000000', long_message)

        # Vérifie ce qui a été envoyé
        call_args = mock_post.call_args
        sent_message = call_args.kwargs['data']['message']
        self.assertEqual(len(sent_message), 160)
        self.assertTrue(sent_message.endswith('...'))

    @patch('apps.notifications.sms.requests.post')
    def test_numero_invalide(self, mock_post):
        """Numéro vide ou invalide → False, pas d'appel HTTP."""
        result = send_sms('', 'Test')
        self.assertFalse(result)
        mock_post.assert_not_called()

        result = send_sms('abc', 'Test')
        self.assertFalse(result)
        mock_post.assert_not_called()

    @patch('apps.notifications.sms.requests.post')
    def test_message_vide(self, mock_post):
        """Message vide → False, pas d'appel HTTP."""
        result = send_sms('0700000000', '')
        self.assertFalse(result)
        mock_post.assert_not_called()

    @patch('apps.notifications.sms.requests.post')
    def test_erreur_reseau(self, mock_post):
        """Erreur réseau → False, pas de crash."""
        import requests
        mock_post.side_effect = requests.RequestException('Connection timeout')

        result = send_sms('0700000000', 'Test')
        self.assertFalse(result)

    @patch('apps.notifications.sms.requests.post')
    def test_payload_envoye_correctement(self, mock_post):
        """Vérifie que le payload envoyé contient les bons champs."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = 'OK'
        mock_post.return_value = mock_resp

        send_sms('0709430661', 'Hello IvoirPass')

        call_args = mock_post.call_args
        data = call_args.kwargs['data']
        self.assertEqual(data['_to'], '2250709430661')
        self.assertEqual(data['message'], 'Hello IvoirPass')
        self.assertEqual(data['_from'], 'DIGITICKETS')
        self.assertEqual(data['country'], 'ivory-coast')