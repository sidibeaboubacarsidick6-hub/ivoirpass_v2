"""
Tests du service SMS — apps/notifications/sms.py

Couvre :
- Cache du token OAuth (2 appels → 1 seul token OAuth)
- Early-return si token None
- Troncature propre à 160 caractères
- Normalisation des numéros (+225, 00XX, espaces, tirets)
- Fallback Twilio si Orange échoue
- Respect de SMS_ENABLED
- Timeout / erreur réseau
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.core.cache import cache

from apps.notifications.sms import (
    OrangeSMSService, TwilioSMSService, send_sms, _normalize_phone,
)


@override_settings(
    SMS_ENABLED=True,
    ORANGE_SMS_CLIENT_ID='client_id_test',
    ORANGE_SMS_CLIENT_SECRET='client_secret_test',
    ORANGE_SMS_SENDER_ADDRESS='+2250700000000',
    ORANGE_SMS_SENDER_NAME='IvoirPass',
    TWILIO_ACCOUNT_SID='',
)
class NormalizePhoneTests(TestCase):
    """Tests de la normalisation du numéro."""

    def test_phone_avec_espaces_et_tirets(self):
        self.assertEqual(
            _normalize_phone('+225 07 00 00 00 00'),
            '+2250700000000',
        )
        self.assertEqual(
            _normalize_phone('+225-07-00-00-00-00'),
            '+2250700000000',
        )

    def test_phone_local_sans_indicatif(self):
        self.assertEqual(
            _normalize_phone('0700000000'),
            '+2250700000000',
        )

    def test_phone_avec_prefixe_225(self):
        self.assertEqual(
            _normalize_phone('2250700000000'),
            '+2250700000000',
        )

    def test_phone_avec_prefixe_00(self):
        self.assertEqual(
            _normalize_phone('002250700000000'),
            '+2250700000000',
        )

    def test_phone_vide_retourne_none(self):
        self.assertIsNone(_normalize_phone(''))
        self.assertIsNone(_normalize_phone(None))


@override_settings(SMS_ENABLED=False)
class SmsDisabledTests(TestCase):
    """Quand SMS_ENABLED=False → tout est loggé, aucun envoi."""

    @patch('apps.notifications.sms.OrangeSMSService.send')
    def test_send_sms_desactive(self, mock_send):
        result = send_sms('+2250700000000', 'Test')
        self.assertTrue(result)  # renvoie True pour ne pas casser le flux
        mock_send.assert_not_called()


@override_settings(
    SMS_ENABLED=True,
    ORANGE_SMS_CLIENT_ID='client_id_test',
    ORANGE_SMS_CLIENT_SECRET='client_secret_test',
    ORANGE_SMS_SENDER_ADDRESS='+2250700000000',
    ORANGE_SMS_SENDER_NAME='IvoirPass',
    TWILIO_ACCOUNT_SID='',
)
class OrangeTokenCacheTests(TestCase):
    """Cache du token OAuth."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.notifications.sms.requests.post')
    def test_token_mis_en_cache(self, mock_post):
        """Un appel OAuth → le token est caché."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'access_token': 'token_abc'}
        mock_post.return_value = mock_resp

        token1 = OrangeSMSService._get_token()
        token2 = OrangeSMSService._get_token()

        self.assertEqual(token1, 'token_abc')
        self.assertEqual(token2, 'token_abc')
        # Un SEUL appel OAuth malgré 2 demandes
        self.assertEqual(mock_post.call_count, 1)

    @patch('apps.notifications.sms.requests.post')
    def test_pas_de_token_dans_reponse_retourne_none(self, mock_post):
        """Pas d'access_token dans la réponse → None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'error': 'invalid_client'}
        mock_resp.status_code = 401
        mock_resp.text = 'Unauthorized'
        mock_post.return_value = mock_resp

        token = OrangeSMSService._get_token()
        self.assertIsNone(token)

    @patch('apps.notifications.sms.requests.post')
    def test_erreur_reseau_retourne_none(self, mock_post):
        """Erreur réseau → None."""
        mock_post.side_effect = Exception('Connection timeout')
        token = OrangeSMSService._get_token()
        self.assertIsNone(token)


@override_settings(
    SMS_ENABLED=True,
    ORANGE_SMS_CLIENT_ID='client_id_test',
    ORANGE_SMS_CLIENT_SECRET='client_secret_test',
    ORANGE_SMS_SENDER_ADDRESS='+2250700000000',
    ORANGE_SMS_SENDER_NAME='IvoirPass',
    TWILIO_ACCOUNT_SID='',
)
class OrangeSendTests(TestCase):
    """Envoi de SMS via Orange."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.notifications.sms.requests.post')
    def test_envoi_success(self, mock_post):
        """Orange retourne 200 → True."""
        token_resp = MagicMock()
        token_resp.json.return_value = {'access_token': 'tok_ok'}
        send_resp = MagicMock()
        send_resp.status_code = 201
        mock_post.side_effect = [token_resp, send_resp]

        result = OrangeSMSService.send('+2250700000000', 'Test SMS')
        self.assertTrue(result)

    @patch('apps.notifications.sms.requests.post')
    def test_envoi_echec_500(self, mock_post):
        """Orange retourne 500 → False."""
        token_resp = MagicMock()
        token_resp.json.return_value = {'access_token': 'tok_x'}
        send_resp = MagicMock()
        send_resp.status_code = 500
        send_resp.text = 'Server error'
        mock_post.side_effect = [token_resp, send_resp]

        result = OrangeSMSService.send('+2250700000000', 'Test')
        self.assertFalse(result)

    @patch('apps.notifications.sms.requests.post')
    def test_troncature_message_trop_long(self, mock_post):
        """Message > 160 chars → tronqué avec ..."""
        token_resp = MagicMock()
        token_resp.json.return_value = {'access_token': 'tok_x'}
        send_resp = MagicMock()
        send_resp.status_code = 201
        mock_post.side_effect = [token_resp, send_resp]

        long_message = 'A' * 300
        OrangeSMSService.send('+2250700000000', long_message)

        # Le 2e appel (send) contient le message tronqué
        send_call = mock_post.call_args_list[1]
        sent_message = send_call.kwargs['json']['outboundSMSMessageRequest']['outboundSMSTextMessage']['message']

        self.assertEqual(len(sent_message), 160)
        self.assertTrue(sent_message.endswith('...'))

    @patch('apps.notifications.sms.requests.post')
    def test_early_return_si_token_none(self, mock_post):
        """Token None → return False SANS envoyer Bearer None."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'error': 'invalid'}
        mock_resp.status_code = 401
        mock_resp.text = ''
        mock_post.return_value = mock_resp

        result = OrangeSMSService.send('+2250700000000', 'Test')
        self.assertFalse(result)
        # Un seul appel (OAuth), pas de 2e appel send
        self.assertEqual(mock_post.call_count, 1)


@override_settings(
    SMS_ENABLED=True,
    ORANGE_SMS_CLIENT_ID='',
    ORANGE_SMS_CLIENT_SECRET='',
    ORANGE_SMS_SENDER_ADDRESS='',
    TWILIO_ACCOUNT_SID='',
)
class NoProviderConfiguredTests(TestCase):
    """Aucun provider configuré → False."""

    def test_aucun_provider_configure(self):
        result = send_sms('+2250700000000', 'Test')
        self.assertFalse(result)


@override_settings(
    SMS_ENABLED=True,
    ORANGE_SMS_CLIENT_ID='client_id_test',
    ORANGE_SMS_CLIENT_SECRET='client_secret_test',
    ORANGE_SMS_SENDER_ADDRESS='+2250700000000',
    ORANGE_SMS_SENDER_NAME='IvoirPass',
    TWILIO_ACCOUNT_SID='',
)
class FallbackTests(TestCase):
    """Fallback Twilio si Orange échoue."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(TWILIO_ACCOUNT_SID='twilio_sid', TWILIO_AUTH_TOKEN='tok', TWILIO_FROM_NUMBER='+1XXX')
    @patch('apps.notifications.sms.TwilioSMSService.send')
    @patch('apps.notifications.sms.OrangeSMSService.send')
    def test_fallback_twilio_si_orange_echoue(self, mock_orange, mock_twilio):
        """Orange échoue → Twilio prend le relais."""
        mock_orange.return_value = False
        mock_twilio.return_value = True

        result = send_sms('+2250700000000', 'Test')
        self.assertTrue(result)
        mock_orange.assert_called_once()
        mock_twilio.assert_called_once()

    @override_settings(TWILIO_ACCOUNT_SID='', TWILIO_AUTH_TOKEN='')
    @patch('apps.notifications.sms.OrangeSMSService.send')
    def test_pas_de_fallback_si_twilio_non_configure(self, mock_orange):
        """Orange échoue + Twilio non configuré → False."""
        mock_orange.return_value = False
        result = send_sms('+2250700000000', 'Test')
        self.assertFalse(result)