"""Régression : une commande boutique invitée annulée ne doit pas ressusciter."""
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.payments.models import Payment
from apps.store.models import Product, ProductCategory, GuestProductOrder
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone



class GuestProductOrderCancelRaceTests(TestCase):
    def _make_order(self):
        seller = CustomUser.objects.create_user(
            email='seller-cancel-race@test.com',
            password='Pass123!',
            role='organizer',
            is_organizer_verified=True,
        )
        category = ProductCategory.objects.create(name='Test Annulation Boutique')
        product = Product.objects.create(
            seller=seller,
            name='Produit test annulation',
            category=category,
            price=5000,
            status=Product.Status.PUBLISHED,
            product_type=Product.ProductType.PHYSICAL,
            stock=10,
        )
        order = GuestProductOrder.objects.create(
            first_name='Test', last_name='Annulation',
            email='buyer-store-cancel-race@test.com',
            product=product, quantity=1, unit_price=5000,
            subtotal=5000, total=5000,
            status=GuestProductOrder.Status.PENDING,
            delivery_method=GuestProductOrder.DeliveryMethod.DELIVERY,
        )
        payment = Payment.objects.create(
            guest_product_order=order, amount=5000,
            provider=Payment.Provider.PAYDUNYA,
            status=Payment.Status.PENDING,
            paydunya_token='fake-store-cancel-race',
        )
        return order, payment

    def test_annulation_boutique_cloture_le_payment(self):
        order, payment = self._make_order()

        Client().get(reverse('store:guest_payment_cancel', kwargs={'order_number': order.order_number}))

        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, GuestProductOrder.Status.CANCELLED)
        self.assertEqual(payment.status, Payment.Status.CANCELLED)

    def test_commande_annulee_ne_peut_plus_etre_confirmee(self):
        order, payment = self._make_order()
        Client().get(reverse('store:guest_payment_cancel', kwargs={'order_number': order.order_number}))

        order.refresh_from_db()
        confirmed = order.mark_as_paid(
            payment_method='paydunya', payment_reference=payment.paydunya_token
        )

        self.assertFalse(confirmed)
        order.refresh_from_db()
        self.assertEqual(order.status, GuestProductOrder.Status.CANCELLED)

    def test_payment_annule_exclu_de_la_reconciliation(self):
        order, payment = self._make_order()
        Client().get(reverse('store:guest_payment_cancel', kwargs={'order_number': order.order_number}))

        candidates = Payment.objects.filter(
            pk=payment.pk, status=Payment.Status.PENDING
        )
        self.assertEqual(candidates.count(), 0)

    def test_annule_reste_bloque_meme_apres_delai(self):
        order, payment = self._make_order()
        order.status = GuestProductOrder.Status.CANCELLED
        order.save(update_fields=['status'])
        payment.status = Payment.Status.CANCELLED
        payment.save(update_fields=['status'])

        # Même en simulant une ancienne annulation, le statut CANCELLED reste terminal.
        order.updated_at = timezone.now() - timedelta(hours=3)
        order.save(update_fields=['updated_at'])
        self.assertFalse(order.mark_as_paid(payment_method='paydunya', payment_reference='late-token'))
        order.refresh_from_db()
        self.assertEqual(order.status, GuestProductOrder.Status.CANCELLED)
