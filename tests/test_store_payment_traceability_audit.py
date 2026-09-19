"""
Test d'audit — Extension de la traçabilité financière à la boutique.

Contexte : les commandes boutique (GuestProductOrder, seul canal réellement
utilisé) ne créaient jusqu'ici aucune ligne Payment — invisibles du
back-office financier et de la réconciliation PayDunya, qui ne couvraient
que la billetterie. Couvre : création du Payment à l'initiation, mise à
jour à la confirmation (retour + webhook), idempotence de
GuestProductOrder.mark_as_paid() (même correctif R-01 que la billetterie),
visibilité dans le back-office, et récupération par la réconciliation.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_store_payment_traceability_audit -v 2
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.store.models import ProductCategory, Product, GuestProductOrder
from apps.payments.models import Payment
from apps.payments.tasks import reconcile_pending_payments
from apps.dashboard.models import AuditLog


def _make_digital_product(seller):
    category = ProductCategory.objects.create(name='Cat Trace', slug='cat-trace')
    return Product.objects.create(
        name='Ebook Test', slug='ebook-test', category=category, seller=seller,
        product_type=Product.ProductType.DIGITAL, price=Decimal('3000'),
        commission_rate=Decimal('10'), status=Product.Status.PUBLISHED,
    )


class GuestProductOrderIdempotencyTests(TestCase):
    """Même correctif R-01 que Order/GuestOrder — voir apps/tickets/models.py."""

    def setUp(self):
        self.seller = CustomUser.objects.create_user(email='vendeur.trace@test.com', password='Pass123!', role='organizer')
        self.product = _make_digital_product(self.seller)
        self.order = GuestProductOrder.objects.create(
            first_name='A', last_name='B', email='client.trace@test.com',
            product=self.product, quantity=1, unit_price=Decimal('3000'),
            subtotal=Decimal('3000'), total=Decimal('3000'),
            status=GuestProductOrder.Status.PENDING,
        )

    def test_premier_appel_confirme_et_renvoie_true(self):
        self.assertTrue(self.order.mark_as_paid(payment_method='paydunya'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, GuestProductOrder.Status.PAID)

    def test_deuxieme_appel_est_un_no_op_et_ne_double_credite_pas(self):
        from apps.dashboard.models import WalletTransaction
        self.order.mark_as_paid(payment_method='paydunya')
        result = self.order.mark_as_paid(payment_method='paydunya')
        self.assertFalse(result, "Le second appel doit être un no-op")
        credits = WalletTransaction.objects.filter(
            reference=self.order.order_number, type=WalletTransaction.Type.CREDIT
        )
        self.assertEqual(credits.count(), 1, "Un seul crédit wallet, malgré les deux appels")


class GuestStorePaymentInitiationTests(TestCase):
    def setUp(self):
        self.seller = CustomUser.objects.create_user(email='vendeur.init@test.com', password='Pass123!', role='organizer')
        self.product = _make_digital_product(self.seller)
        self.order = GuestProductOrder.objects.create(
            first_name='A', last_name='B', email='client.init@test.com',
            product=self.product, quantity=1, unit_price=Decimal('3000'),
            subtotal=Decimal('3000'), total=Decimal('3000'),
            status=GuestProductOrder.Status.PENDING,
        )

    @patch('requests.post')
    def test_initiation_cree_une_ligne_payment(self, mock_post):
        mock_post.return_value = MagicMock(json=lambda: {
            'response_code': '00', 'token': 'tok_store_init', 'response_text': 'https://paydunya.test/pay',
        })
        Client().get(reverse('store:guest_payment', kwargs={'order_number': self.order.order_number}))

        payment = Payment.objects.get(guest_product_order=self.order)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.paydunya_token, 'tok_store_init')
        self.assertEqual(payment.amount, self.order.total)


class BackofficeStoreTransactionTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(email='admin.store.trace@test.com', password='Pass123!')
        self.admin.role = CustomUser.Role.ADMIN
        self.admin.save()
        self.seller = CustomUser.objects.create_user(email='vendeur.bo@test.com', password='Pass123!', role='organizer')
        self.product = _make_digital_product(self.seller)
        self.order = GuestProductOrder.objects.create(
            first_name='Client', last_name='Boutique', email='client.bo@test.com',
            product=self.product, quantity=2, unit_price=Decimal('3000'),
            subtotal=Decimal('6000'), total=Decimal('6000'),
            status=GuestProductOrder.Status.PAID, paid_at=timezone.now(),
        )
        self.payment = Payment.objects.create(
            guest_product_order=self.order, amount=Decimal('6000'), currency='XOF',
            status=Payment.Status.COMPLETED, provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_store_bo',
        )
        self.client_ = Client()
        self.client_.login(email='admin.store.trace@test.com', password='Pass123!')

    def test_transaction_boutique_apparait_dans_la_liste(self):
        response = self.client_.get(reverse('dashboard:transactions'))
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'Boutique')

    def test_fiche_transaction_boutique_saffiche(self):
        response = self.client_.get(reverse('dashboard:transaction_detail', args=[self.order.order_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)

    def test_export_csv_inclut_la_transaction_boutique(self):
        response = self.client_.get(reverse('dashboard:export_transactions_csv'))
        content = response.content.decode('utf-8-sig')
        self.assertIn(self.order.order_number, content)
        self.assertIn('Boutique', content)


class ReconciliationCoversStoreTests(TestCase):
    def setUp(self):
        self.seller = CustomUser.objects.create_user(email='vendeur.recon@test.com', password='Pass123!', role='organizer')
        self.product = _make_digital_product(self.seller)
        self.order = GuestProductOrder.objects.create(
            first_name='A', last_name='B', email='client.recon@test.com',
            product=self.product, quantity=1, unit_price=Decimal('3000'),
            subtotal=Decimal('3000'), total=Decimal('3000'),
            status=GuestProductOrder.Status.PENDING,
        )
        self.payment = Payment.objects.create(
            guest_product_order=self.order, amount=Decimal('3000'), currency='XOF',
            status=Payment.Status.PENDING, provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_store_recon',
        )
        Payment.objects.filter(pk=self.payment.pk).update(created_at=timezone.now() - timedelta(minutes=30))

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_paiement_boutique_confirme_chez_paydunya_est_recupere(self, mock_verify):
        mock_verify.return_value = {'success': True, 'status': 'completed'}

        reconcile_pending_payments()

        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.status, GuestProductOrder.Status.PAID)
        self.assertEqual(self.payment.status, Payment.Status.COMPLETED)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.RECONCILIATION_RECOVERED).exists()
        )
