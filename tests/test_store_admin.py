"""
Tests de l'admin boutique — apps/store/admin.py
"""
from decimal import Decimal

from django.test import TestCase
from django.contrib.admin.sites import AdminSite

from apps.accounts.models import CustomUser
from apps.store.models import Product, ProductCategory, ProductOrder, GuestProductOrder
from apps.store.admin import ProductAdmin, ProductOrderAdmin, GuestProductOrderAdmin


def _make_seller(email='seller@test.com'):
    u = CustomUser.objects.create_user(email=email, password='pass')
    u.role = CustomUser.Role.ORGANIZER
    u.save()
    return u


def _make_category(slug='cat-test'):
    return ProductCategory.objects.create(name=f'Cat {slug}', slug=slug)


def _make_product(seller, category, name='Produit', status='draft'):
    return Product.objects.create(
        name=name, description='d', seller=seller, category=category,
        price=Decimal('1000'), status=status,
    )


class ProductAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = ProductAdmin(Product, self.site)
        self.admin.message_user = lambda *a, **kw: None

    def test_cover_preview_sans_image(self):
        seller = _make_seller('p-cover@test.com')
        cat = _make_category('cat-cover')
        p = _make_product(seller, cat, name='NoImg')
        result = self.admin.cover_preview(p)
        self.assertEqual(result, '—')

    def test_cover_preview_avec_image(self):
        seller = _make_seller('p-cover2@test.com')
        cat = _make_category('cat-cover2')
        p = _make_product(seller, cat, name='WithImg')
        # Mock l'image
        p.cover_image = type('Img', (), {'url': 'http://x/img.jpg'})()
        result = self.admin.cover_preview(p)
        self.assertIn('img', str(result))

    def test_action_publish_products(self):
        seller = _make_seller('p-pub@test.com')
        cat = _make_category('cat-pub')
        p = _make_product(seller, cat, name='P1', status='draft')

        self.admin.publish_products(None, Product.objects.filter(pk=p.pk))

        p.refresh_from_db()
        self.assertEqual(p.status, 'published')

    def test_action_archive_products(self):
        seller = _make_seller('p-arch@test.com')
        cat = _make_category('cat-arch')
        p = _make_product(seller, cat, name='P2', status='published')

        self.admin.archive_products(None, Product.objects.filter(pk=p.pk))

        p.refresh_from_db()
        self.assertEqual(p.status, 'archived')

    def test_action_approve_and_publish(self):
        seller = _make_seller('p-appr@test.com')
        cat = _make_category('cat-appr')
        p = _make_product(seller, cat, name='P3', status='draft')

        self.admin.approve_and_publish(None, Product.objects.filter(pk=p.pk))
        p.refresh_from_db()
        self.assertEqual(p.status, 'published')

    def test_action_reject_to_draft(self):
        seller = _make_seller('p-rej@test.com')
        cat = _make_category('cat-rej')
        p = _make_product(seller, cat, name='P4', status='published')

        self.admin.reject_to_draft(None, Product.objects.filter(pk=p.pk))
        p.refresh_from_db()
        self.assertEqual(p.status, 'draft')


class ProductOrderAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = ProductOrderAdmin(ProductOrder, self.site)
        self.admin.message_user = lambda *a, **kw: None

    def test_action_mark_shipped(self):
        seller = _make_seller('po-ship@test.com')
        cat = _make_category('cat-po')
        p = _make_product(seller, cat, name='PO1', status='published')
        buyer = CustomUser.objects.create_user(email='po-b@test.com', password='p')

        order = ProductOrder.objects.create(
            buyer=buyer, product=p, quantity=1,
            unit_price=Decimal('1000'), subtotal=Decimal('1000'),
            total=Decimal('1000'), status='paid',
        )

        self.admin.mark_shipped(None, ProductOrder.objects.filter(pk=order.pk))

        order.refresh_from_db()
        self.assertEqual(order.status, 'shipped')
        self.assertIsNotNone(order.shipped_at)


class GuestProductOrderAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = GuestProductOrderAdmin(GuestProductOrder, self.site)
        self.admin.message_user = lambda *a, **kw: None

    def test_get_buyer_name(self):
        seller = _make_seller('gpo-s@test.com')
        cat = _make_category('cat-gpo')
        p = _make_product(seller, cat, name='GPO1', status='published')

        order = GuestProductOrder.objects.create(
            first_name='Ali', last_name='B', email='g@test.com',
            product=p, quantity=1, unit_price=Decimal('1000'),
            subtotal=Decimal('1000'), total=Decimal('1000'),
            status='pending',
        )
        self.assertEqual(self.admin.get_buyer_name(order), 'Ali B')

    def test_action_mark_shipped_guest(self):
        seller = _make_seller('gpo-s2@test.com')
        cat = _make_category('cat-gpo2')
        p = _make_product(seller, cat, name='GPO2', status='published')

        order = GuestProductOrder.objects.create(
            first_name='Ali', last_name='B', email='g2@test.com',
            product=p, quantity=1, unit_price=Decimal('1000'),
            subtotal=Decimal('1000'), total=Decimal('1000'),
            status='paid',
        )

        self.admin.mark_shipped(
            None, GuestProductOrder.objects.filter(pk=order.pk),
        )

        order.refresh_from_db()
        self.assertEqual(order.status, 'shipped')