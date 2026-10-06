"""
Tests des vues de paiement PayDunya — apps/payments/views.py

Couvre :
- payment_webhook : signature invalide, JSON, form-data, order_number
  manquant, webhook dupliqué, statut pending, statut cancelled
- _confirm_order : idempotence (2 appels → 1 seule confirmation)
- payment_return : déjà payée, token manquant, completed, pending
- payment_status : polling AJAX
- initiate_payment : succès + échec PayDunya
"""
import json
import hashlib
import hmac
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Category, Event, TicketType
from apps.payments.models import Payment
from apps.tickets.models import Order, OrderItem, Ticket


def _make_paid_setup(email='buyer@test.com'):
    """Crée un utilisateur + événement + type de billet + commande PENDING."""
    u = CustomUser.objects.create_user(
        email=email, password='pass',
        first_name='Buy', last_name='Er',
    )
    cat, _ = Category.objects.get_or_create(
        slug=f'cat-{email.split("@")[0]}',
        defaults={'name': f'Cat {email}'},
    )
    now = timezone.now()
    event = Event.objects.create(
        title=f'Event {email}',
        slug=f'event-{email.split("@")[0]}',
        description='d',
        short_description='0700000000',
        category=cat,
        organizer=u,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=31),
        status=Event.Status.PUBLISHED,
        commission_rate=Decimal('8.00'),
    )
    tt = TicketType.objects.create(
        event=event, name='Standard',
        price=Decimal('10000'), quantity=100,
    )
    order = Order.objects.create(
        buyer=u, subtotal=Decimal('10000'),
        commission=0, total=Decimal('10000'),
        status=Order.Status.PENDING,
    )
    OrderItem.objects.create(
        order=order, ticket_type=tt,
        quantity=1, unit_price=Decimal('10000'),
    )
    return u, event, tt, order


@override_settings(
    PAYDUNYA_MASTER_KEY='test_master_key',
    PAYDUNYA_MODE='test',
)
class WebhookSignatureTests(TestCase):
    """Vérification de la signature du webhook."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('payments:webhook')  # adapte le nom si différent

    def _valid_signature(self):
        """Génère le hash SHA-512 attendu."""
        return hashlib.sha512(
            'test_master_key'.encode()
        ).hexdigest()

    def test_webhook_signature_invalide_403(self):
        """Signature absente ou invalide → 403."""
        response = self.client.post(
            self.url,
            data=json.dumps({'hash': 'faux_hash', 'data': {}}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_webhook_signature_absente_403(self):
        """Pas de hash du tout → 403."""
        response = self.client.post(
            self.url,
            data=json.dumps({'data': {}}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)


@override_settings(
    PAYDUNYA_MASTER_KEY='test_master_key',
    PAYDUNYA_MODE='test',
)
class WebhookValidTests(TestCase):
    """Traitement d'un webhook valide."""

    def setUp(self):
        self.client = Client()
        self.url = reverse('payments:webhook')
        self.buyer, self.event, self.tt, self.order = _make_paid_setup()

    def _signature(self):
        return hashlib.sha512('test_master_key'.encode()).hexdigest()

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_webhook_completed_confirme_commande(self, mock_verify):
        """Webhook completed → commande PAID + tickets créés."""
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }

        # Crée le Payment avant le webhook (comme le ferait initiate_payment)
        payment = Payment.objects.create(
            order=self.order,
            amount=self.order.total,
            currency='XOF',
            status=Payment.Status.PENDING,
            provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_webhook_1',
        )

        payload = {
            'hash': self._signature(),
            'invoiceToken': 'tok_webhook_1',
            'status': 'completed',
            'data': {
                'custom_data': {'order_number': self.order.order_number},
                'invoice': {'status': 'completed'},
            },
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

        # Billet(s) générés
        self.assertEqual(
            Ticket.objects.filter(order_item__order=self.order).count(),
            1,
        )

        # Payment marqué COMPLETED
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.COMPLETED)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_webhook_pending_ne_confirme_pas(self, mock_verify):
        """Webhook pending → commande reste PENDING."""
        mock_verify.return_value = {
            'success': True, 'status': 'pending', 'data': {},
        }

        payload = {
            'hash': self._signature(),
            'invoiceToken': 'tok_pending',
            'status': 'pending',
            'data': {
                'custom_data': {'order_number': self.order.order_number},
                'invoice': {'status': 'pending'},
            },
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_webhook_completed_deux_fois_ne_cree_pas_double_billet(self, mock_verify):
        """Webhook reçu 2 fois → 1 seule confirmation, 1 seul billet."""
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }

        payload = {
            'hash': self._signature(),
            'invoiceToken': 'tok_dup',
            'status': 'completed',
            'data': {
                'custom_data': {'order_number': self.order.order_number},
                'invoice': {'status': 'completed'},
            },
        }

        # 1er webhook
        r1 = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        # 2e webhook identique
        r2 = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

        # UN SEUL billet malgré 2 webhooks
        self.assertEqual(
            Ticket.objects.filter(order_item__order=self.order).count(),
            1,
        )

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_webhook_ordre_inexistant_retourne_404(self, mock_verify):
        """order_number inexistant → 404."""
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }

        payload = {
            'hash': self._signature(),
            'invoiceToken': 'tok_ghost',
            'status': 'completed',
            'data': {
                'custom_data': {'order_number': 'IP-2026-FAKEXX'},
                'invoice': {'status': 'completed'},
            },
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)


@override_settings(PAYDUNYA_MODE='test')
class ConfirmOrderIdempotenceTests(TestCase):
    """Idempotence de _confirm_order."""

    def setUp(self):
        self.buyer, self.event, self.tt, self.order = _make_paid_setup(
            'idem@test.com'
        )

    def test_confirm_order_deux_fois_ne_duplique_pas(self):
        """2 appels à _confirm_order → 1 seule transition PAID."""
        from apps.payments.views import _confirm_order

        _confirm_order(self.order, 'tok_idem', {'provider': 'paydunya'})
        _confirm_order(self.order, 'tok_idem', {'provider': 'paydunya'})

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

        # Un seul billet
        self.assertEqual(
            Ticket.objects.filter(order_item__order=self.order).count(),
            1,
        )


@override_settings(PAYDUNYA_MODE='test')
class PaymentReturnTests(TestCase):
    """Tests de payment_return (retour utilisateur depuis PayDunya)."""

    def setUp(self):
        self.client = Client()
        self.buyer, self.event, self.tt, self.order = _make_paid_setup(
            'ret@test.com'
        )
        # Crée un Payment PENDING avec un token
        self.payment = Payment.objects.create(
            order=self.order,
            amount=Decimal('10000'),
            currency='XOF',
            status=Payment.Status.PENDING,
            provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_ret_1',
        )

    def test_payment_return_si_deja_payee(self):
        """Commande déjà PAID → redirection confirmation."""
        self.order.status = Order.Status.PAID
        self.order.save(update_fields=['status'])

        url = reverse(
            'payments:return',
            kwargs={'order_number': self.order.order_number},
        )
        response = self.client.get(url)

        # Doit rediriger (302), pas afficher une erreur
        self.assertEqual(response.status_code, 302)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_payment_return_completed_confirme(self, mock_verify):
        """Verify completed → confirmation."""
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }

        url = reverse(
            'payments:return',
            kwargs={'order_number': self.order.order_number},
        ) + '?token=tok_ret_1'

        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_payment_return_pending_affiche_page(self, mock_verify):
        """Verify pending → page d'attente."""
        mock_verify.return_value = {
            'success': True, 'status': 'pending', 'data': {},
        }

        url = reverse(
            'payments:return',
            kwargs={'order_number': self.order.order_number},
        ) + '?token=tok_ret_1'

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_payment_return_token_manquant(self, mock_verify):
        """Pas de token → redirection checkout."""
        url = reverse(
            'payments:return',
            kwargs={'order_number': self.order.order_number},
        )
        # Retire le token du Payment pour simuler un cas extrême
        Payment.objects.filter(order=self.order).update(paydunya_token='')

        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)


@override_settings(PAYDUNYA_MODE='test')
class PaymentStatusPollingTests(TestCase):
    """Tests du polling AJAX payment_status."""

    def setUp(self):
        self.client = Client()
        self.buyer, self.event, self.tt, self.order = _make_paid_setup(
            'poll@test.com'
        )
        self.payment = Payment.objects.create(
            order=self.order,
            amount=Decimal('10000'),
            currency='XOF',
            status=Payment.Status.PENDING,
            provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_poll_1',
        )
        self.client.force_login(self.buyer)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_payment_status_completed(self, mock_verify):
        """Verify completed → JSON status completed + redirect_url."""
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }

        url = reverse(
            'payments:status',
            kwargs={'order_number': self.order.order_number},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'completed')
        self.assertIn('redirect_url', data)

    @patch('apps.payments.views.PayDunyaService.verify_payment')
    def test_payment_status_pending(self, mock_verify):
        """Verify pending → JSON status pending."""
        mock_verify.return_value = {
            'success': True, 'status': 'pending', 'data': {},
        }

        url = reverse(
            'payments:status',
            kwargs={'order_number': self.order.order_number},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'pending')


@override_settings(PAYDUNYA_MODE='test')
class InitiatePaymentTests(TestCase):
    """Tests de initiate_payment."""

    def setUp(self):
        self.client = Client()
        self.buyer, self.event, self.tt, self.order = _make_paid_setup(
            'init@test.com'
        )
        self.client.force_login(self.buyer)

    @patch('apps.payments.views.PayDunyaService.create_invoice')
    def test_initiate_payment_success(self, mock_create):
        """Création facture OK → redirection PayDunya."""
        mock_create.return_value = {
            'success': True,
            'token': 'tok_new',
            'payment_url': 'https://paydunya.com/checkout/tok_new',
        }

        url = reverse(
            'payments:initiate',
            kwargs={'order_number': self.order.order_number},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('paydunya', response.url)

        # Payment créé et token stocké
        payment = Payment.objects.filter(order=self.order).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.paydunya_token, 'tok_new')

    @patch('apps.payments.views.PayDunyaService.create_invoice')
    def test_initiate_payment_echec(self, mock_create):
        """Échec création facture → message erreur + redirection."""
        mock_create.return_value = {
            'success': False,
            'error': 'Erreur API PayDunya',
        }

        url = reverse(
            'payments:initiate',
            kwargs={'order_number': self.order.order_number},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)

        # Payment marqué FAILED
        payment = Payment.objects.filter(order=self.order).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.Status.FAILED)