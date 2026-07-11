"""
Test d'audit — Paiements (partie la plus sensible : l'argent).
Couvre : verify_payment (bypass test_), verify_webhook_signature,
payment_webhook de bout en bout, payment_return, non-régression auto-login.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_payments_audit -v 2
"""
import hashlib
import json
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.tickets.models import Order
from apps.payments.models import Payment
from apps.payments.paydunya import PayDunyaService


class VerifyPaymentTestBypassTests(TestCase):
    """Le bypass des tokens 'test_' ne doit fonctionner qu'en mode test."""

    @override_settings(PAYDUNYA_MODE='test')
    def test_token_test_accepte_en_mode_test(self):
        result = PayDunyaService.verify_payment('test_abc123')
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')

    @override_settings(PAYDUNYA_MODE='live')
    def test_token_test_rejete_en_mode_production(self):
        result = PayDunyaService.verify_payment('test_abc123')
        self.assertFalse(result['success'])
        self.assertNotEqual(result['status'], 'completed')

    @override_settings(PAYDUNYA_MODE='live')
    def test_token_normal_ne_bypass_pas_en_prod(self):
        """Un vrai token en mode live doit appeler l'API PayDunya (pas de bypass)."""
        with patch('apps.payments.paydunya.requests.get') as mock_get:
            mock_get.side_effect = Exception("Pas de vraie connexion réseau en test")
            result = PayDunyaService.verify_payment('real_token_xyz')
            self.assertTrue(mock_get.called, "L'API PayDunya doit être appelée pour un token non-test_")
            self.assertFalse(result['success'])


class VerifyWebhookSignatureTests(TestCase):
    """Vérifie la logique du hash SHA-512, conformément au protocole PayDunya."""

    def _make_request(self, body_dict):
        from django.test import RequestFactory
        rf = RequestFactory()
        return rf.post(
            '/payments/webhook/',
            data=json.dumps(body_dict),
            content_type='application/json',
        )

    def test_hash_correct_accepte(self):
        master_key = settings.PAYDUNYA_MASTER_KEY or 'clef-de-test'
        with self.settings(PAYDUNYA_MASTER_KEY=master_key):
            correct_hash = hashlib.sha512(master_key.encode('utf-8')).hexdigest()
            request = self._make_request({'hash': correct_hash, 'status': 'completed'})
            self.assertTrue(PayDunyaService.verify_webhook_signature(request))

    def test_hash_incorrect_rejete(self):
        with self.settings(PAYDUNYA_MASTER_KEY='clef-de-test'):
            request = self._make_request({'hash': 'faux_hash_evidemment_invalide'})
            self.assertFalse(PayDunyaService.verify_webhook_signature(request))

    def test_hash_absent_rejete(self):
        with self.settings(PAYDUNYA_MASTER_KEY='clef-de-test'):
            request = self._make_request({'status': 'completed'})
            self.assertFalse(PayDunyaService.verify_webhook_signature(request))

    def test_body_non_json_ne_plante_pas(self):
        from django.test import RequestFactory
        rf = RequestFactory()
        request = rf.post('/payments/webhook/', data=b'ceci-n-est-pas-du-json', content_type='application/json')
        self.assertFalse(PayDunyaService.verify_webhook_signature(request))

    def test_verify_webhook_signature_ne_leve_pas_nameerror(self):
        """Non-régression du bug 'hmac non importé' déjà rencontré une fois."""
        request = self._make_request({'hash': 'peu importe'})
        try:
            PayDunyaService.verify_webhook_signature(request)
        except NameError as e:
            self.fail(f"verify_webhook_signature a levé une NameError (import manquant) : {e}")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class PaymentWebhookEndToEndTests(TestCase):
    """Teste le webhook complet, comme s'il était appelé par PayDunya."""

    def setUp(self):
        self.client = Client()
        self.buyer = CustomUser.objects.create_user(
            email="acheteur@test.com", password="Pass123!",
            first_name="Ache", last_name="Teur",
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            subtotal=Decimal('10000'),
            commission=Decimal('500'),
            total=Decimal('10500'),
            status=Order.Status.PENDING,
        )
        self.payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total,
            currency='XOF',
            status=Payment.Status.PENDING,
            provider=Payment.Provider.PAYDUNYA,
            paydunya_token='test_webhook_token_1',
        )

    def _valid_hash_body(self, extra=None):
        master_key = settings.PAYDUNYA_MASTER_KEY or 'clef-de-test'
        correct_hash = hashlib.sha512(master_key.encode('utf-8')).hexdigest()
        body = {
            'hash': correct_hash,
            'status': 'completed',
            'invoiceToken': 'test_webhook_token_1',
            'data': {'custom_data': {'order_number': self.order.order_number}},
        }
        if extra:
            body.update(extra)
        return body, master_key

    def test_webhook_signature_invalide_rejete_403(self):
        response = self.client.post(
            reverse('payments:webhook'),
            data=json.dumps({'hash': 'invalide', 'status': 'completed'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING, "Une signature invalide ne doit JAMAIS confirmer la commande")

    def test_webhook_signature_valide_confirme_la_commande(self):
        body, master_key = self._valid_hash_body()
        with self.settings(PAYDUNYA_MASTER_KEY=master_key):
            response = self.client.post(
                reverse('payments:webhook'),
                data=json.dumps(body),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_webhook_ne_plante_jamais_meme_avec_donnees_invalides(self):
        """Non-régression du bug UnboundLocalError déjà rencontré (token référencé avant assignation)."""
        response = self.client.post(
            reverse('payments:webhook'),
            data=b'n-importe-quoi-pas-du-json-du-tout',
            content_type='application/json',
        )
        self.assertIn(response.status_code, (200, 400, 403), "Le webhook doit répondre proprement, jamais planter en 500")

    def test_webhook_double_appel_ne_double_pas_la_confirmation(self):
        """Idempotence : un webhook rejoué ne doit pas re-déclencher la confirmation."""
        body, master_key = self._valid_hash_body()
        with self.settings(PAYDUNYA_MASTER_KEY=master_key):
            self.client.post(reverse('payments:webhook'), data=json.dumps(body), content_type='application/json')
            response2 = self.client.post(reverse('payments:webhook'), data=json.dumps(body), content_type='application/json')
        self.assertEqual(response2.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)


class PaymentReturnSecurityTests(TestCase):
    """Non-régression : payment_return ne doit plus connecter automatiquement l'acheteur."""

    def setUp(self):
        self.client = Client()
        self.buyer = CustomUser.objects.create_user(
            email="acheteur2@test.com", password="Pass123!",
            first_name="Ache", last_name="Teur",
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            subtotal=Decimal('5000'),
            commission=Decimal('250'),
            total=Decimal('5250'),
            status=Order.Status.PENDING,
        )
        Payment.objects.create(
            order=self.order, amount=self.order.total, currency='XOF',
            status=Payment.Status.PENDING, provider=Payment.Provider.PAYDUNYA,
            paydunya_token='test_return_token_1',
        )

    @override_settings(PAYDUNYA_MODE='test', CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=False)
    def test_visiteur_anonyme_pas_connecte_apres_retour_paiement(self):
        """Un visiteur non authentifié qui suit le lien de retour ne doit PAS se retrouver connecté."""
        url = reverse('payments:return', kwargs={'order_number': self.order.order_number})
        self.client.get(url, {'token': 'test_return_token_1'})

        # Vérifie qu'aucune session utilisateur n'a été ouverte pour ce visiteur anonyme
        self.assertNotIn('_auth_user_id', self.client.session)
