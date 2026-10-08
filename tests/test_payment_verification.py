"""
Tests unitaires pour apps/payments/verification.py.

Couverture :
  - Mode test : skip de la vérification
  - Token manquant : rejet
  - Montant manquant (data vide) : rejet
  - Montant égal : acceptation
  - Montant inférieur / supérieur : rejet
  - Normalisation string / int → Decimal
  - Payment introuvable : rejet
  - Binding mismatch (payment lié à une autre commande) : rejet
  - Fallback : total_amount au niveau racine de data
  - Exception inattendue : capturée, retour sans crash

Ces tests sont purement unitaires : ils ne passent PAS par les webhooks
HTTP. Les tests d'intégration webhook vivent dans les suites existantes.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.payments.models import Payment
from apps.payments.verification import verify_payment_amount_and_binding
from apps.tickets.models import Order


User = get_user_model()


class VerifyPaymentAmountAndBindingTests(TestCase):
    """Tests unitaires sur la fonction de vérification."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='verify-test@example.com',
            password='test1234-verif',
        )
        self.order = Order.objects.create(
            buyer=self.user,
            total=Decimal('5000'),
        )
        self.token = 'test_token_xyz_abc'
        self.payment = Payment.objects.create(
            order=self.order,
            paydunya_token=self.token,
            amount=Decimal('5000'),
            status=Payment.Status.PENDING,
        )
        self.verify_result = {
            'success': True,
            'status': 'completed',
            'data': {'invoice': {'total_amount': '5000'}},
        }

    # ------------------------------------------------------------------
    # Mode test → skip
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='test')
    def test_mode_test_skip(self):
        result = verify_payment_amount_and_binding(
            self.verify_result, self.order, self.token,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['reason'], 'test_mode_skip')

    # ------------------------------------------------------------------
    # Token manquant
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_token_manquant_rejette(self):
        result = verify_payment_amount_and_binding(
            self.verify_result, self.order, '',
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'token_missing')

    # ------------------------------------------------------------------
    # Montant manquant
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_absent_rejette(self):
        verify_result = {'success': True, 'status': 'completed', 'data': {}}
        result = verify_payment_amount_and_binding(
            verify_result, self.order, self.token,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'amount_missing')

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_egal_accepte(self):
        result = verify_payment_amount_and_binding(
            self.verify_result, self.order, self.token,
        )
        self.assertTrue(result['ok'])
        self.assertEqual(result['reason'], 'ok')
        self.assertEqual(result['expected'], Decimal('5000'))
        self.assertEqual(result['received'], Decimal('5000'))

    # ------------------------------------------------------------------
    # Montant inférieur / supérieur
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_inferieur_rejette(self):
        verify_result = {
            'success': True, 'status': 'completed',
            'data': {'invoice': {'total_amount': '100'}},
        }
        result = verify_payment_amount_and_binding(
            verify_result, self.order, self.token,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'amount_mismatch')
        self.assertEqual(result['expected'], Decimal('5000'))
        self.assertEqual(result['received'], Decimal('100'))

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_superieur_rejette(self):
        verify_result = {
            'success': True, 'status': 'completed',
            'data': {'invoice': {'total_amount': '6000'}},
        }
        result = verify_payment_amount_and_binding(
            verify_result, self.order, self.token,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'amount_mismatch')

    # ------------------------------------------------------------------
    # Normalisation string / int → Decimal
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_string_egal_decimal_accepte(self):
        verify_result = {
            'success': True, 'status': 'completed',
            'data': {'invoice': {'total_amount': '5000'}},
        }
        result = verify_payment_amount_and_binding(
            verify_result, self.order, self.token,
        )
        self.assertTrue(result['ok'])

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_int_egal_accepte(self):
        verify_result = {
            'success': True, 'status': 'completed',
            'data': {'invoice': {'total_amount': 5000}},
        }
        result = verify_payment_amount_and_binding(
            verify_result, self.order, self.token,
        )
        self.assertTrue(result['ok'])

    # ------------------------------------------------------------------
    # Payment introuvable
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_payment_introuvable_rejette(self):
        result = verify_payment_amount_and_binding(
            self.verify_result, self.order, 'token_qui_nexiste_pas',
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'payment_not_found')

    # ------------------------------------------------------------------
    # Binding mismatch : le payment pointe vers une autre commande
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_binding_mismatch_rejette(self):
        other_order = Order.objects.create(
            buyer=self.user,
            total=Decimal('5000'),
        )
        # On déplace le payment vers other_order
        self.payment.order = other_order
        self.payment.save(update_fields=['order'])
        # Mais on demande la confirmation de self.order
        result = verify_payment_amount_and_binding(
            self.verify_result, self.order, self.token,
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'binding_mismatch')

    # ------------------------------------------------------------------
    # Fallback : total_amount à la racine de data
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    def test_montant_fallback_top_level(self):
        verify_result = {
            'success': True, 'status': 'completed',
            'data': {'total_amount': '5000'},
        }
        result = verify_payment_amount_and_binding(
            verify_result, self.order, self.token,
        )
        self.assertTrue(result['ok'])

    # ------------------------------------------------------------------
    # Exception inattendue capturée
    # ------------------------------------------------------------------

    @override_settings(PAYDUNYA_MODE='live')
    @patch('apps.payments.models.Payment.objects.filter')
    def test_exception_inattendue_capturee(self, mock_filter):
        mock_filter.side_effect = RuntimeError('Simulated DB failure')
        result = verify_payment_amount_and_binding(
            self.verify_result, self.order, self.token,
        )
        self.assertFalse(result['ok'])
        self.assertIn('unexpected_error', result['reason'])
