"""
IvoirPass V2 — Tests étape 3 : KYC obligatoire + fix bundle + fix stock.

Couvre les cas #7, #10, #11 du chantier, plus la régression des bugs
cancel/refund de GuestProductOrder (stock non restauré).

Cas fonctionnels testés :
  #7  - Organisateur non KYC → publication produit bloquée + message
  #10 - Bundle stock=0 → achetable en version numérique seule
  #11 - Bundle stock=0 → version physique bloquée
  + Régression : cancel() et refund() restaurent le stock
    UNIQUEMENT quand la livraison physique avait été engagée.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import CustomUser
from apps.store.models import (
    Product, ProductCategory,
    GuestProductOrder, GuestDownloadLink,
)


# ============================================================
# Helpers
# ============================================================

def _make_organizer(email='org@test.com', kyc=True):
    """
    Crée un utilisateur organisateur.

    - Rôle positionné via `role = CustomUser.Role.ORGANIZER`
      (`is_organizer` est une @property calculée depuis `role`).
    - KYC positionné via le BooleanField `is_organizer_verified`
      — c'est le vrai signal utilisé par la billetterie
      (apps/events/views.py:218).
    """
    user = CustomUser.objects.create_user(
        email=email,
        password='testpass123',
        first_name='Org', last_name='Test',
    )
    user.role = CustomUser.Role.ORGANIZER
    user.is_organizer_verified = kyc
    if kyc:
        user.kyc_verified_at = timezone.now()
    user.save()
    return user


def _make_category(name='Musique'):
    return ProductCategory.objects.create(name=name)


def _make_product(seller, category, **kwargs):
    defaults = {
        'name': 'Produit Test',
        'description': 'desc',
        'product_type': Product.ProductType.DIGITAL,
        'price': 2000,
        'status': Product.Status.PUBLISHED,
        'seller': seller,
        'category': category,
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


# ============================================================
# TEST #7 — KYC obligatoire pour publier un produit
# ============================================================

class KYCPublishProductTests(TestCase):
    """Cas #7 : un organisateur non KYC ne peut pas publier."""

    def setUp(self):
        self.category = _make_category()

    def _form_data(self):
        return {
            'name': 'Album KYC Test',
            'description': 'desc test',
            'category': self.category.pk,
            'product_type': Product.ProductType.DIGITAL,
            'external_url': 'https://open.spotify.com/album/kyctest',
            'price': 2000,
            'stock': 0,
            'status': Product.Status.PUBLISHED,
        }

    def test_publish_without_kyc_is_blocked_with_message(self):
        user = _make_organizer(kyc=False)
        self.client.force_login(user)

        before_count = Product.objects.count()
        response = self.client.post(
            reverse('store:product_create'), data=self._form_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KYC')
        self.assertContains(response, 'CNI')
        self.assertEqual(Product.objects.count(), before_count)

    def test_publish_with_kyc_succeeds(self):
        user = _make_organizer(kyc=True)
        self.client.force_login(user)

        response = self.client.post(
            reverse('store:product_create'), data=self._form_data(),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Product.objects.filter(name='Album KYC Test').exists(),
        )

    def test_save_as_draft_without_kyc_is_allowed(self):
        """Un brouillon n'est pas concerné par la garde KYC."""
        user = _make_organizer(kyc=False)
        self.client.force_login(user)

        data = self._form_data()
        data['status'] = Product.Status.DRAFT

        response = self.client.post(
            reverse('store:product_create'), data=data,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Product.objects.filter(name='Album KYC Test').exists(),
        )

    def test_get_product_create_returns_200(self):
        """
        Régression : la vue product_create doit retourner la page sur un
        GET (500 observé en preprod le 2026-09-27 — le `return render`
        final avait été perdu lors d'un copier-coller).
        """
        user = _make_organizer(kyc=True)
        self.client.force_login(user)

        response = self.client.get(reverse('store:product_create'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'store/product_form.html',
            [t.name for t in response.templates],
        )


# ============================================================
# TEST #10 / #11 — Bundle stock=0
# ============================================================

class BundleStockZeroTests(TestCase):
    """Bundle avec stock=0 : numérique OK, physique bloqué."""

    def setUp(self):
        self.seller = _make_organizer()
        self.category = _make_category()
        self.product = _make_product(
            self.seller, self.category,
            name='Bundle Épuisé',
            product_type=Product.ProductType.BUNDLE,
            external_url='https://bandcamp.com/album/bundle',
            price=3000,
            price_physical=3000,
            price_digital=1500,
            stock=0,
        )

    def test_is_available_true_for_bundle_stock_zero(self):
        self.assertTrue(self.product.is_available)
        self.assertFalse(self.product.is_available_physical)
        self.assertTrue(self.product.is_available_digital)

    def test_buy_digital_only_when_stock_zero_is_allowed(self):
        """Cas #10 : bundle stock=0 + delivery=download → OK."""
        response = self.client.post(
            reverse('store:guest_buy', kwargs={'slug': self.product.slug}),
            data={
                'first_name': 'Jean',
                'last_name': 'Acheteur',
                'email': 'acheteur@test.com',
                'phone': '+225 07 00 00 00 00',
                'quantity': 1,
                'delivery_method': 'download',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GuestProductOrder.objects.filter(
                email='acheteur@test.com',
                delivery_method=GuestProductOrder.DeliveryMethod.DOWNLOAD,
            ).exists()
        )

    def test_buy_physical_when_stock_zero_is_blocked(self):
        """Cas #11 : bundle stock=0 + delivery=delivery → refusé."""
        response = self.client.post(
            reverse('store:guest_buy', kwargs={'slug': self.product.slug}),
            data={
                'first_name': 'Jean',
                'last_name': 'Acheteur',
                'email': 'acheteur@test.com',
                'phone': '+225 07 00 00 00 00',
                'quantity': 1,
                'delivery_method': 'delivery',
                'delivery_name': 'Jean Acheteur',
                'delivery_phone': '+225 07 00 00 00 00',
                'delivery_address': 'Cocody Angré 7e tranche',
                'delivery_city': 'Abidjan',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'épuisée')
        self.assertFalse(
            GuestProductOrder.objects.filter(email='acheteur@test.com').exists()
        )


# ============================================================
# RÉGRESSION — cancel/refund restaurent bien le stock
# ============================================================

class GuestOrderCancelRestoreStockTests(TestCase):
    """Vérifie que cancel() et refund() restaurent le stock."""

    def setUp(self):
        self.seller = _make_organizer()
        self.category = _make_category()

    def _make_paid_order(self, delivery_method, quantity=2, initial_stock=10):
        product = _make_product(
            self.seller, self.category,
            name=f'Produit {delivery_method}',
            product_type=Product.ProductType.BUNDLE,
            external_url='https://bandcamp.com/album/test',
            price=3000,
            price_physical=3000,
            price_digital=1500,
            stock=initial_stock,
        )
        order = GuestProductOrder.objects.create(
            first_name='Jean', last_name='Acheteur',
            email='acheteur@test.com',
            product=product,
            quantity=quantity,
            unit_price=product.price,
            subtotal=product.price * quantity,
            total=product.price * quantity,
            delivery_method=delivery_method,
            status=GuestProductOrder.Status.PAID,
            paid_at=timezone.now(),
        )
        return product, order

    def test_cancel_after_physical_purchase_restores_stock(self):
        """Si la livraison physique avait été engagée, cancel restaure."""
        product, order = self._make_paid_order(
            GuestProductOrder.DeliveryMethod.DELIVERY,
            quantity=2, initial_stock=10,
        )
        product.stock = 8
        product.save(update_fields=['stock'])

        order.cancel()

        product.refresh_from_db()
        self.assertEqual(product.stock, 10)
        self.assertEqual(order.status, GuestProductOrder.Status.CANCELLED)

    def test_cancel_pure_digital_does_not_touch_stock(self):
        """Achat 100% numérique : cancel NE DOIT PAS gonfler le stock."""
        product, order = self._make_paid_order(
            GuestProductOrder.DeliveryMethod.DOWNLOAD,
            quantity=2, initial_stock=10,
        )
        order.cancel()

        product.refresh_from_db()
        self.assertEqual(product.stock, 10)

    def test_refund_after_physical_purchase_restores_stock(self):
        product, order = self._make_paid_order(
            GuestProductOrder.DeliveryMethod.DELIVERY,
            quantity=2, initial_stock=10,
        )
        product.stock = 8
        product.save(update_fields=['stock'])

        order.refund()

        product.refresh_from_db()
        self.assertEqual(product.stock, 10)
        self.assertEqual(order.status, GuestProductOrder.Status.REFUNDED)

    def test_refund_pure_digital_does_not_touch_stock(self):
        product, order = self._make_paid_order(
            GuestProductOrder.DeliveryMethod.DOWNLOAD,
            quantity=2, initial_stock=10,
        )
        order.refund()

        product.refresh_from_db()
        self.assertEqual(product.stock, 10)

    def test_cancel_twice_is_idempotent(self):
        """Deux cancel() ne doivent pas restituer 2× le stock."""
        product, order = self._make_paid_order(
            GuestProductOrder.DeliveryMethod.DELIVERY,
            quantity=2, initial_stock=10,
        )
        product.stock = 8
        product.save(update_fields=['stock'])

        order.cancel()
        order.cancel()

        product.refresh_from_db()
        self.assertEqual(product.stock, 10)