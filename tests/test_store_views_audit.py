"""
Test d'audit — Flux boutique complet (apps/store/views.py, 11% de
couverture avant cet audit). Couvre l'achat, la protection IDOR sur la
gestion produit, et le téléchargement sécurisé des fichiers numériques.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_store_views_audit -v 2
"""
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import CustomUser
from apps.store.models import Product, ProductCategory, ProductOrder, DownloadLink


def _make_seller_and_product(seller_email='seller-store@test.com', stock=10, product_type='physical', price=5000):
    seller = CustomUser.objects.create_user(
        email=seller_email, password='Pass123!', role='organizer', is_organizer_verified=True,
    )
    category = ProductCategory.objects.create(name=f'Cat-{seller_email}', slug=f'cat-{seller_email}'.replace('@', '-').replace('.', '-'))
    product = Product.objects.create(
        seller=seller, category=category, name='Produit Test', description='Description test',
        product_type=product_type, price=price, stock=stock, status=Product.Status.PUBLISHED,
    )
    return seller, product


class StoreListAndDetailTests(TestCase):

    def setUp(self):
        cache.clear()  # store_list est mis en cache — isole chaque test

    def test_store_list_affiche_les_produits_publies(self):
        seller, product = _make_seller_and_product()
        client = Client()
        response = client.get(reverse('store:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.name)

    def test_store_list_cache_les_brouillons(self):
        seller, product = _make_seller_and_product()
        product.status = Product.Status.DRAFT
        product.save()
        client = Client()
        response = client.get(reverse('store:list'))
        self.assertNotContains(response, product.name)

    def test_store_detail_produit_existant(self):
        seller, product = _make_seller_and_product()
        client = Client()
        response = client.get(reverse('store:detail', kwargs={'slug': product.slug}))
        self.assertEqual(response.status_code, 200)


class BuyProductStockTests(TestCase):
    """Vérifie le verrouillage de stock déjà en place (select_for_update)."""

    def setUp(self):
        self.seller, self.product = _make_seller_and_product(stock=1)
        self.buyer = CustomUser.objects.create_user(email='buyer-store@test.com', password='Pass123!')

    def test_achat_avec_stock_suffisant_cree_une_commande(self):
        client = Client()
        client.force_login(self.buyer)
        response = client.post(
            reverse('store:buy', kwargs={'slug': self.product.slug}),
            {'quantity': 1, 'delivery_method': 'delivery',
             'delivery_name': 'Test', 'delivery_phone': '+2250700000000',
             'delivery_address': 'Cocody', 'delivery_city': 'Abidjan'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProductOrder.objects.filter(buyer=self.buyer, product=self.product).exists())

    def test_achat_avec_stock_insuffisant_refuse(self):
        client = Client()
        client.force_login(self.buyer)
        response = client.post(
            reverse('store:buy', kwargs={'slug': self.product.slug}),
            {'quantity': 5, 'delivery_method': 'delivery',
             'delivery_name': 'Test', 'delivery_phone': '+2250700000000',
             'delivery_address': 'Cocody', 'delivery_city': 'Abidjan'},
        )
        self.assertFalse(ProductOrder.objects.filter(buyer=self.buyer, product=self.product).exists())

    def test_produit_physique_sans_adresse_refuse(self):
        client = Client()
        client.force_login(self.buyer)
        response = client.post(
            reverse('store:buy', kwargs={'slug': self.product.slug}),
            {'quantity': 1, 'delivery_method': 'delivery'},
        )
        self.assertEqual(response.status_code, 200)  # re-render du formulaire, pas de redirection
        self.assertFalse(ProductOrder.objects.filter(buyer=self.buyer, product=self.product).exists())


class ProductManagementIDORTests(TestCase):
    """Un vendeur ne doit jamais pouvoir gérer le produit d'un autre vendeur."""

    def setUp(self):
        self.seller_a, self.product_a = _make_seller_and_product('seller-a@test.com')
        self.seller_b, self.product_b = _make_seller_and_product('seller-b@test.com')

    def test_vendeur_ne_peut_pas_modifier_le_produit_dun_autre(self):
        client = Client()
        client.force_login(self.seller_b)
        response = client.get(reverse('store:product_edit', kwargs={'slug': self.product_a.slug}))
        self.assertEqual(response.status_code, 404)

    def test_vendeur_ne_peut_pas_supprimer_le_produit_dun_autre(self):
        client = Client()
        client.force_login(self.seller_b)
        client.post(reverse('store:product_delete', kwargs={'slug': self.product_a.slug}))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.status, Product.Status.PUBLISHED, "Le produit ne doit pas avoir été supprimé/archivé")

    def test_vendeur_peut_modifier_son_propre_produit(self):
        client = Client()
        client.force_login(self.seller_a)
        response = client.get(reverse('store:product_edit', kwargs={'slug': self.product_a.slug}))
        self.assertEqual(response.status_code, 200)


class SecureDownloadTests(TestCase):
    """Le téléchargement d'un fichier numérique doit être strictement réservé à l'acheteur."""

    def setUp(self):
        self.seller, self.product = _make_seller_and_product(product_type='digital')
        self.product.digital_file = SimpleUploadedFile("fichier.txt", b"contenu du produit numerique")
        self.product.save()

        self.buyer = CustomUser.objects.create_user(email='buyer-dl@test.com', password='Pass123!')
        self.other_user = CustomUser.objects.create_user(email='autre-dl@test.com', password='Pass123!')

        order = ProductOrder.objects.create(
            buyer=self.buyer, product=self.product, quantity=1,
            unit_price=self.product.price, subtotal=self.product.price, total=self.product.price,
            delivery_method='download', status=ProductOrder.Status.PAID,
        )
        self.link = DownloadLink.objects.create(
            order=order, product=self.product,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_acheteur_peut_telecharger(self):
        client = Client()
        client.force_login(self.buyer)
        response = client.get(reverse('store:download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 200)

    def test_autre_utilisateur_ne_peut_pas_telecharger(self):
        client = Client()
        client.force_login(self.other_user)
        response = client.get(reverse('store:download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 404)

    def test_visiteur_non_connecte_redirige_vers_login(self):
        client = Client()
        response = client.get(reverse('store:download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 302)

    def test_lien_expire_refuse(self):
        self.link.expires_at = timezone.now() - timedelta(days=1)
        self.link.save()

        client = Client()
        client.force_login(self.buyer)
        response = client.get(reverse('store:download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 302)  # redirigé vers order_detail avec message d'erreur

    def test_limite_de_telechargements_atteinte_refuse(self):
        self.link.download_count = self.link.max_downloads
        self.link.save()

        client = Client()
        client.force_login(self.buyer)
        response = client.get(reverse('store:download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 302)
