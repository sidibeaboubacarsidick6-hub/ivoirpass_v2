"""
Tests unitaires du service FeexPay (mockés).
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from apps.payments.feexpay import FeexPayService


@override_settings(
    FEEXPAY_API_TOKEN='fp_test_token',
    FEEXPAY_SHOP_ID='shop_test_123',
    FEEXPAY_BASE_URL='https://api-v2.feexpay.me',
)
class FeexPayServiceTests(TestCase):

    def _make_order(self, total=200, phone='+2250700000000'):
        order = MagicMock()
        order.total = Decimal(str(total))
        order.phone = phone
        order.order_number = 'IP-2026-TEST'
        order.first_name = 'Jean'
        order.last_name = 'Dupont'
        order.email = 'jean@test.com'
        order.buyer_name = 'Jean Dupont'
        order.access_token = 'token-abc'
        return order

    # ------------------------------------------------------------------
    # create_invoice
    # ------------------------------------------------------------------
    @patch('apps.payments.feexpay.requests.post')
    def test_create_invoice_wave_ci(self, mock_post):
        """Un numéro 07 doit router vers wave_ci."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'reference': 'ref-uuid-123',
            'status': 'PENDING',
            'amount': 200,
            'payment_url': 'https://sandbox-wave.example.com/pay/ref-uuid-123',
        }
        mock_post.return_value = mock_resp

        order = self._make_order(phone='+2250700000000')
        result = FeexPayService.create_invoice(order, None)

        # Nouveau format normalisé
        self.assertTrue(result['success'])
        self.assertEqual(result['provider_reference'], 'ref-uuid-123')
        self.assertEqual(
            result['payment_url'],
            'https://sandbox-wave.example.com/pay/ref-uuid-123',
        )

        args, kwargs = mock_post.call_args
        self.assertIn('/requesttopay/wave_ci', args[0])
        self.assertEqual(kwargs['json']['amount'], 200)
        self.assertEqual(kwargs['json']['shop'], 'shop_test_123')
        self.assertEqual(
            kwargs['headers']['Authorization'], 'Bearer fp_test_token',
        )

    @patch('apps.payments.feexpay.requests.post')
    def test_create_invoice_mtn_ci(self, mock_post):
        """Un numéro 05 doit router vers mtn_ci."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'reference': 'ref-mtn', 'status': 'PENDING', 'amount': 200,
        }
        mock_post.return_value = mock_resp

        order = self._make_order(phone='+2250500000000')
        FeexPayService.create_invoice(order, None)

        args, _ = mock_post.call_args
        self.assertIn('/requesttopay/mtn_ci', args[0])

    # ------------------------------------------------------------------
    # verify_payment
    # ------------------------------------------------------------------
    @patch('apps.payments.feexpay.requests.get')
    def test_verify_payment_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'reference': 'ref-123', 'status': 'SUCCESSFUL', 'amount': 200,
        }
        mock_get.return_value = mock_resp

        result = FeexPayService.verify_payment('ref-123')
        # Nouveau format : SUCCESSFUL → status='completed' + success=True
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['amount'], 200)

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------
    def test_verify_webhook_signature_always_true(self):
        """FeexPay ne signe pas — on retourne True (vérif via API)."""
        self.assertTrue(FeexPayService.verify_webhook_signature(None))

    def test_parse_webhook(self):
        """Extraction et normalisation du payload FeexPay."""
        import json
        request = MagicMock()
        request.body = json.dumps({
            'reference': 'ref-123',
            'status': 'SUCCESSFUL',
            'amount': 200,
            'callback_info': 'IP-2026-TEST',
            'reseau': 'WAVE CI',
        }).encode()

        data = FeexPayService.parse_webhook(request)
        # Nouveau format : provider_reference + status normalisé
        self.assertEqual(data['provider_reference'], 'ref-123')
        self.assertEqual(data['status'], 'completed')
        self.assertEqual(data['order_number'], 'IP-2026-TEST')
        self.assertEqual(data['raw']['reseau'], 'WAVE CI')


class FeexPayPhoneNormalizationTests(TestCase):

    def test_phone_without_prefix_gets_225(self):
        from apps.payments.feexpay import FeexPayService
        self.assertEqual(
            FeexPayService._normalize_phone('0700000000'),
            '2250700000000',
        )

    def test_phone_with_plus_prefix(self):
        from apps.payments.feexpay import FeexPayService
        self.assertEqual(
            FeexPayService._normalize_phone('+2250700000000'),
            '2250700000000',
        )

    def test_phone_with_spaces(self):
        from apps.payments.feexpay import FeexPayService
        self.assertEqual(
            FeexPayService._normalize_phone('+225 07 00 00 00 00'),
            '2250700000000',
        )

    def test_phone_already_normalized(self):
        from apps.payments.feexpay import FeexPayService
        self.assertEqual(
            FeexPayService._normalize_phone('2250700000000'),
            '2250700000000',
        )

    def test_phone_none_returns_225(self):
        from apps.payments.feexpay import FeexPayService
        self.assertEqual(FeexPayService._normalize_phone(None), '225')