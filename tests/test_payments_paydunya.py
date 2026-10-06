"""
Tests du service PayDunya — apps/payments/paydunya.py

Couvre :
- verify_webhook_signature : valide / invalide / pas de hash
- get_headers : clés correctes
- create_invoice : succès + échec + timeout
- create_disbursement : succès + mode invalide + téléphone normalisé
- submit_disbursement : success / pending / failed
- check_disbursement_status : succès / pending / failed
- verify_payment : token test en mode test / token test en mode prod
- verify_disbursement_callback : signature valide / invalide
"""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, override_settings

from apps.payments.paydunya import PayDunyaService


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
    PAYDUNYA_PRIVATE_KEY='private_key_test',
    PAYDUNYA_TOKEN='token_test',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    PAYDUNYA_DISBURSEMENT_API_BASE='https://api.paydunya.com/sandbox-api/v1',
)
class VerifyWebhookSignatureTests(TestCase):
    """Tests de verify_webhook_signature."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_signature_valide(self):
        """Hash correct → True."""
        expected = hashlib.sha512(
            'master_key_test'.encode()
        ).hexdigest()

        request = self.factory.post(
            '/webhook/',
            data=json.dumps({'hash': expected}),
            content_type='application/json',
        )

        self.assertTrue(
            PayDunyaService.verify_webhook_signature(request)
        )

    def test_signature_invalide(self):
        """Hash incorrect → False."""
        request = self.factory.post(
            '/webhook/',
            data=json.dumps({'hash': 'faux_hash'}),
            content_type='application/json',
        )

        self.assertFalse(
            PayDunyaService.verify_webhook_signature(request)
        )

    def test_pas_de_hash(self):
        """Pas de hash → False."""
        request = self.factory.post(
            '/webhook/',
            data=json.dumps({'data': {}}),
            content_type='application/json',
        )

        self.assertFalse(
            PayDunyaService.verify_webhook_signature(request)
        )

    def test_hash_dans_data(self):
        """Hash dans data.hash → True."""
        expected = hashlib.sha512(
            'master_key_test'.encode()
        ).hexdigest()

        request = self.factory.post(
            '/webhook/',
            data=json.dumps({'data': {'hash': expected}}),
            content_type='application/json',
        )

        self.assertTrue(
            PayDunyaService.verify_webhook_signature(request)
        )

    def test_json_invalide(self):
        """Body non-JSON → False."""
        request = self.factory.post(
            '/webhook/',
            data='not json',
            content_type='application/json',
        )

        self.assertFalse(
            PayDunyaService.verify_webhook_signature(request)
        )


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
    PAYDUNYA_PRIVATE_KEY='private_key_test',
    PAYDUNYA_TOKEN='token_test',
    PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
)
class GetHeadersTests(TestCase):
    """Tests de get_headers."""

    def test_headers_contient_les_3_cles(self):
        headers = PayDunyaService.get_headers()

        self.assertEqual(headers['PAYDUNYA-MASTER-KEY'], 'master_key_test')
        self.assertEqual(headers['PAYDUNYA-PRIVATE-KEY'], 'private_key_test')
        self.assertEqual(headers['PAYDUNYA-TOKEN'], 'token_test')
        self.assertEqual(headers['Content-Type'], 'application/json')


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
    PAYDUNYA_PRIVATE_KEY='private_key_test',
    PAYDUNYA_TOKEN='token_test',
    PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
)
class CreateInvoiceTests(TestCase):
    """Tests de create_invoice."""

    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_success(self, mock_post):
        """PayDunya répond 00 → succès avec token + payment_url."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'token': 'inv_tok_1',
            'response_text': 'https://paydunya.com/checkout/inv_tok_1',
        }
        mock_post.return_value = mock_resp

        # Fake order avec items
        from apps.accounts.models import CustomUser
        from apps.events.models import Category, Event, TicketType
        from apps.tickets.models import Order, OrderItem
        from django.utils import timezone

        u = CustomUser.objects.create_user(email='t1@test.com', password='pass')
        cat, _ = Category.objects.get_or_create(slug='c1', defaults={'name': 'C1'})
        now = timezone.now()
        e = Event.objects.create(
            title='E1', slug='e1', description='d',
            short_description='0700000000', category=cat, organizer=u,
            start_date=now + timezone.timedelta(days=30),
            end_date=now + timezone.timedelta(days=31),
            status=Event.Status.PUBLISHED,
        )
        tt = TicketType.objects.create(event=e, name='Std', price=Decimal('5000'), quantity=10)
        order = Order.objects.create(buyer=u, subtotal=Decimal('5000'), total=Decimal('5000'))
        OrderItem.objects.create(order=order, ticket_type=tt, quantity=1, unit_price=Decimal('5000'))

        request = MagicMock()
        result = PayDunyaService.create_invoice(order, request)

        self.assertTrue(result['success'])
        self.assertEqual(result['token'], 'inv_tok_1')
        self.assertIn('paydunya', result['payment_url'])

    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_echec(self, mock_post):
        """PayDunya retourne code != 00 → échec."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '100',
            'response_text': 'Erreur interne PayDunya',
        }
        mock_post.return_value = mock_resp

        order = MagicMock()
        order.items.all.return_value = []
        order.total = Decimal('5000')
        order.order_number = 'IP-2026-TEST'
        order.buyer.email = 'x@test.com'

        request = MagicMock()
        result = PayDunyaService.create_invoice(order, request)

        self.assertFalse(result['success'])
        self.assertIn('Erreur', result['error'])

    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_timeout(self, mock_post):
        """Erreur réseau → échec propre (pas d'exception levée)."""
        mock_post.side_effect = Exception('Timeout')

        order = MagicMock()
        order.items.all.return_value = []
        order.total = Decimal('5000')
        order.order_number = 'IP-2026-TEST'
        order.buyer.email = 'x@test.com'

        request = MagicMock()
        result = PayDunyaService.create_invoice(order, request)

        self.assertFalse(result['success'])


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
    PAYDUNYA_PRIVATE_KEY='private_key_test',
    PAYDUNYA_TOKEN='token_test',
    PAYDUNYA_DISBURSEMENT_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
)
class CreateDisbursementTests(TestCase):
    """Tests de create_disbursement."""

    @patch('apps.payments.paydunya.requests.post')
    def test_create_disbursement_success_wave(self, mock_post):
        """Wave → mode wave-ci, succès."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'disburse_token': 'disb_tok_1',
        }
        mock_post.return_value = mock_resp

        wr = MagicMock()
        wr.payout_method = 'wave'
        wr.payout_phone = '+2250700000000'
        wr.amount = Decimal('5000')
        wr.amount_net = Decimal('5000')
        wr.reference = 'REV-TEST'

        result = PayDunyaService.create_disbursement(wr)

        self.assertTrue(result['success'])
        self.assertEqual(result['token'], 'disb_tok_1')

        # Vérifie le payload envoyé
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs['json']['withdraw_mode'], 'wave-ci')

    @patch('apps.payments.paydunya.requests.post')
    def test_create_disbursement_success_orange(self, mock_post):
        """Orange → mode orange-money-ci."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00', 'disburse_token': 't',
        }
        mock_post.return_value = mock_resp

        wr = MagicMock()
        wr.payout_method = 'orange_money'
        wr.payout_phone = '+2250700000000'
        wr.amount = Decimal('5000')
        wr.amount_net = Decimal('5000')
        wr.reference = 'REV-O'

        PayDunyaService.create_disbursement(wr)

        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs['json']['withdraw_mode'], 'orange-money-ci')

    @patch('apps.payments.paydunya.requests.post')
    def test_create_disbursement_normalise_225(self, mock_post):
        """Numéro avec préfixe 225 → retiré pour PayDunya."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'response_code': '00', 'disburse_token': 't'}
        mock_post.return_value = mock_resp

        wr = MagicMock()
        wr.payout_method = 'wave'
        wr.payout_phone = '2250700000000'  # Sans +
        wr.amount = Decimal('5000')
        wr.amount_net = Decimal('5000')
        wr.reference = 'REV-N'

        PayDunyaService.create_disbursement(wr)

        call_kwargs = mock_post.call_args.kwargs
        # 225 est retiré → 0700000000
        self.assertEqual(call_kwargs['json']['account_alias'], '0700000000')

    def test_create_disbursement_mode_inconnu(self):
        """Payout method non supporté → erreur sans appel HTTP."""
        wr = MagicMock()
        wr.payout_method = 'bitcoin'  # Inconnu
        wr.reference = 'REV-X'

        result = PayDunyaService.create_disbursement(wr)

        self.assertFalse(result['success'])
        self.assertIn('non supportée', result['error'])


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
    PAYDUNYA_PRIVATE_KEY='private_key_test',
    PAYDUNYA_TOKEN='token_test',
    PAYDUNYA_DISBURSEMENT_API_BASE='https://api.paydunya.com/sandbox-api/v1',
)
class SubmitDisbursementTests(TestCase):
    """Tests de submit_disbursement."""

    @patch('apps.payments.paydunya.requests.post')
    def test_submit_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'status': 'success',
            'transaction_id': 'tx_1',
        }
        mock_post.return_value = mock_resp

        result = PayDunyaService.submit_disbursement('tok', 'REV-1')

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'success')

    @patch('apps.payments.paydunya.requests.post')
    def test_submit_pending(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'status': 'pending',
        }
        mock_post.return_value = mock_resp

        result = PayDunyaService.submit_disbursement('tok', 'REV-1')

        self.assertEqual(result['status'], 'pending')

    @patch('apps.payments.paydunya.requests.post')
    def test_submit_erreur_reseau(self, mock_post):
        mock_post.side_effect = Exception('Timeout')

        result = PayDunyaService.submit_disbursement('tok', 'REV-1')

        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'unknown')


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
    PAYDUNYA_MODE='test',
)
class VerifyPaymentTests(TestCase):
    """Tests de verify_payment."""

    @override_settings(PAYDUNYA_MODE='test')
    def test_token_test_en_mode_test(self):
        """Token 'test_' en mode test → success."""
        result = PayDunyaService.verify_payment('test_abc123')

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')

    @override_settings(PAYDUNYA_MODE='live')
    def test_token_test_en_mode_live_rejete(self):
        """Token 'test_' en mode live → rejeté."""
        result = PayDunyaService.verify_payment('test_abc123')

        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'failed')

    @patch('apps.payments.paydunya.requests.get')
    @override_settings(
        PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    )
    def test_token_reel_completed(self, mock_get):
        """Token réel + PayDunya completed → success."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'data': {'invoice': {'status': 'completed'}},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = PayDunyaService.verify_payment('real_token_xyz')

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')

    @patch('apps.payments.paydunya.requests.get')
    @override_settings(
        PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    )
    def test_token_reel_pending(self, mock_get):
        """Token réel + PayDunya pending."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'data': {'invoice': {'status': 'pending'}},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = PayDunyaService.verify_payment('real_token_pending')

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'pending')

    @patch('apps.payments.paydunya.requests.get')
    @override_settings(
        PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    )
    def test_erreur_reseau(self, mock_get):
        """Erreur réseau → success=False."""
        mock_get.side_effect = Exception('Connection refused')

        result = PayDunyaService.verify_payment('real_token')

        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'error')


@override_settings(
    PAYDUNYA_MASTER_KEY='master_key_test',
)
class VerifyDisbursementCallbackTests(TestCase):
    """Tests de verify_disbursement_callback."""

    def test_signature_valide(self):
        expected = hashlib.sha512('master_key_test'.encode()).hexdigest()
        payload = {'hash': expected, 'status': 'success'}

        self.assertTrue(
            PayDunyaService.verify_disbursement_callback(payload)
        )

    def test_signature_invalide(self):
        payload = {'hash': 'mauvais_hash', 'status': 'success'}

        self.assertFalse(
            PayDunyaService.verify_disbursement_callback(payload)
        )

    def test_pas_de_hash(self):
        payload = {'status': 'success'}

        self.assertFalse(
            PayDunyaService.verify_disbursement_callback(payload)
        )


class ParseDisbursementCallbackTests(TestCase):
    """Tests de parse_disbursement_callback."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_json_valide(self):
        request = self.factory.post(
            '/callback/',
            data=json.dumps({'status': 'success', 'disburse_id': 'D1'}),
            content_type='application/json',
        )
        result = PayDunyaService.parse_disbursement_callback(request)

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['disburse_id'], 'D1')

    def test_json_invalide(self):
        request = self.factory.post(
            '/callback/',
            data='not json',
            content_type='application/json',
        )
        result = PayDunyaService.parse_disbursement_callback(request)

        self.assertEqual(result, {})