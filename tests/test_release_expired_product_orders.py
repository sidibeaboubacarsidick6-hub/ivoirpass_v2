"""
Tests de la tâche release_expired_pending_product_orders.

Vérifie la logique 2 vitesses sur les commandes boutique (ProductOrder
et GuestProductOrder), + l'annulation automatique des Payment PENDING.
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.payments.models import Payment
from apps.payments.tasks import release_expired_pending_product_orders
from apps.store.models import Product, ProductCategory, GuestProductOrder


User = get_user_model()


class ReleaseExpiredProductOrdersTests(TestCase):

    def setUp(self):
        self.seller = User.objects.create_user(
            email='seller@test.com', password='test1234',
            first_name='S', last_name='E',
            role=User.Role.ORGANIZER,
        )
        self.cat = ProductCategory.objects.create(
            name='Test Cat', slug='test-cat',
        )
        self.product = Product.objects.create(
            name='Test Product',
            slug='test-product',
            description='d',
            short_description='0700000000',
            category=self.cat,
            seller=self.seller,
            product_type='digital',
            price=Decimal('5000'),
            status=Product.Status.PUBLISHED,
        )

    def _create_pending_order(self, minutes_old, has_token=False):
        order = GuestProductOrder.objects.create(
            first_name='B', last_name='E',
            email=f'b-{minutes_old}-{has_token}@test.com',
            phone='+2250700000000',
            product=self.product,
            quantity=1,
            unit_price=Decimal('5000'),
            total=Decimal('5000'),
            delivery_method=GuestProductOrder.DeliveryMethod.DOWNLOAD,
            status=GuestProductOrder.Status.PENDING,
        )
        Payment.objects.create(
            guest_product_order=order,
            amount=Decimal('5000'),
            status=Payment.Status.PENDING,
            paydunya_token='tok_abc' if has_token else '',
        )
        old_date = timezone.now() - timedelta(minutes=minutes_old)
        GuestProductOrder.objects.filter(pk=order.pk).update(created_at=old_date)
        order.refresh_from_db()
        return order

    def test_no_token_old_order_cancelled(self):
        """Sans token, > 30 min → annulée + Payment CANCELLED."""
        order = self._create_pending_order(45, has_token=False)
        release_expired_pending_product_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, GuestProductOrder.Status.CANCELLED)
        payment = Payment.objects.get(guest_product_order=order)
        self.assertEqual(payment.status, Payment.Status.CANCELLED)

    def test_token_but_recent_order_kept(self):
        """Avec token, 2h → conservée."""
        order = self._create_pending_order(120, has_token=True)
        release_expired_pending_product_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, GuestProductOrder.Status.PENDING)

    def test_token_and_old_order_cancelled(self):
        """Avec token, > 24h → annulée + Payment CANCELLED."""
        order = self._create_pending_order(25 * 60, has_token=True)
        release_expired_pending_product_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, GuestProductOrder.Status.CANCELLED)
        payment = Payment.objects.get(guest_product_order=order)
        self.assertEqual(payment.status, Payment.Status.CANCELLED)
