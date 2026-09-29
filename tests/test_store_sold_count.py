"""
Tests du fix 2026-09-29 : Product.sold_count doit compter TOUTES les
ventes (physiques + numériques + bundles both).

Bug corrigé : `sold_count` n'était incrémenté que pour les ventes
physiques (delivery/both), pas pour les ventes numériques seules
(download) → le compteur affiché était inférieur au vrai nombre de
ventes.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.store.models import Product, ProductCategory, GuestProductOrder


def _make_seller(email='s@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='S', last_name='T',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_product(seller, product_type='bundle', stock=10):
    cat, _ = ProductCategory.objects.get_or_create(name='Test')
    return Product.objects.create(
        name='Livre+Album', description='d',
        product_type=product_type, price=5000,
        price_physical=3000, price_digital=2500,
        seller=seller, category=cat,
        status=Product.Status.PUBLISHED,
        stock=stock,
    )


def _make_order(product, delivery_method):
    return GuestProductOrder.objects.create(
        first_name='Jean', last_name='A',
        email='buyer@test.com',
        product=product, quantity=1,
        unit_price=product.price, subtotal=product.price, total=product.price,
        delivery_method=delivery_method,
        status=GuestProductOrder.Status.PENDING,
    )


class SoldCountFixTests(TestCase):
    """Vérifie que sold_count compte toutes les ventes."""

    def setUp(self):
        self.seller = _make_seller()
        self.bundle = _make_product(self.seller, 'bundle')

    def test_physical_only_incremente_sold_count(self):
        order = _make_order(self.bundle, 'delivery')
        order.mark_as_paid(payment_method='paydunya', payment_reference='t1')
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.sold_count, 1)
        self.assertEqual(self.bundle.stock, 9)

    def test_download_only_incremente_sold_count_sans_toucher_stock(self):
        """Le fix principal : download seul compte dans sold_count."""
        order = _make_order(self.bundle, 'download')
        order.mark_as_paid(payment_method='paydunya', payment_reference='t2')
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.sold_count, 1, "sold_count doit compter la vente numérique")
        self.assertEqual(self.bundle.stock, 10, "le stock physique ne doit PAS bouger")

    def test_both_incremente_sold_count_et_decremente_stock(self):
        order = _make_order(self.bundle, 'both')
        order.mark_as_paid(payment_method='paydunya', payment_reference='t3')
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.sold_count, 1)
        self.assertEqual(self.bundle.stock, 9)

    def test_scenario_3_ventes_mixtes_sold_count_egal_3(self):
        """Le scénario utilisateur : physique + numérique + both = 3."""
        o1 = _make_order(self.bundle, 'delivery')
        o1.mark_as_paid(payment_method='paydunya', payment_reference='t4')

        o2 = _make_order(self.bundle, 'download')
        o2.mark_as_paid(payment_method='paydunya', payment_reference='t5')

        o3 = _make_order(self.bundle, 'both')
        o3.mark_as_paid(payment_method='paydunya', payment_reference='t6')

        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.sold_count, 3, "sold_count doit valoir 3 (avant fix : 2)")
        # Stock : décrémenté pour physical + both = 8
        self.assertEqual(self.bundle.stock, 8)

    def test_produit_digital_pur_incremente_sold_count(self):
        digital = _make_product(self.seller, 'digital', stock=0)
        order = _make_order(digital, 'download')
        order.mark_as_paid(payment_method='paydunya', payment_reference='t7')
        digital.refresh_from_db()
        self.assertEqual(digital.sold_count, 1)
        self.assertEqual(digital.stock, 0)  # pas de stock pour digital