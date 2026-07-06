"""
IvoirPass V2 — Tests de la boutique culturelle
"""
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import CustomUser
from apps.store.models import Product, ProductCategory, ProductOrder, DownloadLink
from django.utils import timezone


class ProductModelTest(TestCase):

    def setUp(self):
        self.seller = CustomUser.objects.create_user(
            email='seller@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        self.category = ProductCategory.objects.create(
            name='Livres', slug='livres', icon='bi-book',
        )
        self.product = Product.objects.create(
            name        = 'Père Riche Père Pauvre CI',
            description = 'Le classique adapté au contexte ivoirien',
            seller      = self.seller,
            category    = self.category,
            product_type= 'digital',
            price       = 5000,
            status      = 'published',
        )

    def test_product_creation(self):
        self.assertEqual(self.product.name, 'Père Riche Père Pauvre CI')
        self.assertEqual(self.product.product_type, 'digital')
        self.assertEqual(self.product.price, 5000)

    def test_product_slug_generated(self):
        self.assertIsNotNone(self.product.slug)

    def test_digital_product_is_digital(self):
        self.assertTrue(self.product.is_digital)
        self.assertFalse(self.product.is_physical)

    def test_physical_product(self):
        physical = Product.objects.create(
            name='Album CD', description='CD physique',
            seller=self.seller, product_type='physical',
            price=3000, stock=50, status='published',
        )
        self.assertTrue(physical.is_physical)
        self.assertFalse(physical.is_digital)
        self.assertTrue(physical.is_available)

    def test_product_out_of_stock(self):
        product = Product.objects.create(
            name='Livre épuisé', description='Plus de stock',
            seller=self.seller, product_type='physical',
            price=2000, stock=0, status='published',
        )
        self.assertFalse(product.is_available)

    def test_commission_rate_default(self):
        self.assertEqual(float(self.product.commission_rate), 8.0)


class ProductOrderTest(TestCase):

    def setUp(self):
        self.seller = CustomUser.objects.create_user(
            email='seller@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='IvoirPass2026!',
            role='participant',
        )
        self.product = Product.objects.create(
            name='Ebook Test', description='Test',
            seller=self.seller, product_type='digital',
            price=5000, status='published',
            download_limit=3, download_expiry_hours=48,
        )

    def test_order_number_generated(self):
        order = ProductOrder.objects.create(
            buyer      = self.buyer,
            product    = self.product,
            quantity   = 1,
            unit_price = 5000,
            subtotal   = 5000,
            total      = 5000,
        )
        self.assertTrue(order.order_number.startswith('ST-'))

    def test_download_link_generated_after_payment(self):
        order = ProductOrder.objects.create(
            buyer=self.buyer, product=self.product,
            quantity=1, unit_price=5000,
            subtotal=5000, total=5000,
        )
        order.mark_as_paid(
            payment_method    = 'wave',
            payment_reference = 'WAVE-TEST-001',
        )
        links = DownloadLink.objects.filter(order=order)
        self.assertEqual(links.count(), 1)
        self.assertTrue(links.first().is_valid)

    def test_download_link_expires(self):
        order = ProductOrder.objects.create(
            buyer=self.buyer, product=self.product,
            quantity=1, unit_price=5000,
            subtotal=5000, total=5000,
        )
        order.mark_as_paid(payment_method='test', payment_reference='REF')
        link = DownloadLink.objects.get(order=order)

        # Simule expiration
        link.expires_at = timezone.now() - timezone.timedelta(hours=1)
        link.save()
        self.assertFalse(link.is_valid)
        self.assertTrue(link.is_expired)

    def test_download_limit_exhausted(self):
        order = ProductOrder.objects.create(
            buyer=self.buyer, product=self.product,
            quantity=1, unit_price=5000,
            subtotal=5000, total=5000,
        )
        order.mark_as_paid(payment_method='test', payment_reference='REF2')
        link = DownloadLink.objects.get(order=order)

        # Simule 3 téléchargements
        link.download_count = 3
        link.save()
        self.assertFalse(link.is_valid)
        self.assertTrue(link.is_exhausted)
        self.assertEqual(link.downloads_remaining, 0)


class StoreViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.seller = CustomUser.objects.create_user(
            email='seller@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        self.product = Product.objects.create(
            name='Album Test', description='Test album',
            seller=self.seller, product_type='digital',
            price=3000, status='published',
        )

    def test_store_list_public(self):
        response = self.client.get(reverse('store:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Album Test')

    def test_store_detail_public(self):
        response = self.client.get(
            reverse('store:detail', kwargs={'slug': self.product.slug})
        )
        self.assertEqual(response.status_code, 200)

    def test_my_orders_requires_login(self):
        response = self.client.get(reverse('store:my_orders'))
        self.assertEqual(response.status_code, 302)

    def test_my_products_requires_login(self):
        response = self.client.get(reverse('store:my_products'))
        self.assertEqual(response.status_code, 302)

    def test_my_products_organizer(self):
        self.client.login(username='seller@test.com', password='IvoirPass2026!')
        response = self.client.get(reverse('store:my_products'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Album Test')