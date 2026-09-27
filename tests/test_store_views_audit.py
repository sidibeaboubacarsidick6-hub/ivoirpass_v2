"""
Test d'audit — Flux boutique complet (apps/store/views.py, 11% de
couverture avant cet audit). Couvre l'achat, la protection IDOR sur la
gestion produit, et le téléchargement sécurisé des fichiers numériques.

✅ H-3 (audit) : BuyProductStockTests et SecureDownloadTests ciblaient à
l'origine le tunnel d'achat "avec compte" (store:buy, store:download),
retiré/réduit à une redirection car mort (le vrai tunnel actif est le
parcours invité — guest_buy_product / guest_download_file). Réécrits
ci-dessous pour exercer le tunnel réellement actif ; ProductManagementIDORTests
et StoreListAndDetailTests n'étaient pas concernées, inchangées.

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
from apps.store.models import Product, ProductCategory, GuestProductOrder, GuestDownloadLink


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
    """Vérifie le contrôle de stock du tunnel d'achat invité (guest_buy_product)."""

    def setUp(self):
        self.seller, self.product = _make_seller_and_product(stock=1)

    def _post(self, quantity, **extra):
        data = {
            'first_name': 'Test', 'last_name': 'Acheteur',
            'email': 'buyer-store@test.com', 'phone': '+2250700000000',
            'quantity': quantity, 'delivery_method': 'delivery',
        }
        data.update(extra)
        return Client().post(reverse('store:guest_buy', kwargs={'slug': self.product.slug}), data)

    def test_achat_avec_stock_suffisant_cree_une_commande(self):
        response = self._post(
            1, delivery_name='Test', delivery_phone='+2250700000000',
            delivery_address='Cocody', delivery_city='Abidjan',
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GuestProductOrder.objects.filter(email='buyer-store@test.com', product=self.product).exists())

    def test_achat_avec_stock_insuffisant_refuse(self):
        response = self._post(
            5, delivery_name='Test', delivery_phone='+2250700000000',
            delivery_address='Cocody', delivery_city='Abidjan',
        )
        self.assertFalse(GuestProductOrder.objects.filter(email='buyer-store@test.com', product=self.product).exists())

    def test_produit_physique_sans_adresse_refuse(self):
        response = self._post(1)  # delivery_method='delivery' sans adresse
        self.assertEqual(response.status_code, 200)  # re-render du formulaire, pas de redirection
        self.assertFalse(GuestProductOrder.objects.filter(email='buyer-store@test.com', product=self.product).exists())


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
    """
    Le téléchargement d'un fichier numérique invité repose sur un token
    non-devinable (UUID), pas sur une session utilisateur — il n'y a donc
    pas de notion de « autre utilisateur » comme dans le tunnel avec compte.
    La sécurité tient à l'expiration et à la limite de téléchargements.
    """

    def setUp(self):
        self.seller, self.product = _make_seller_and_product(product_type='digital')
        self.product.digital_file = SimpleUploadedFile("fichier.txt", b"contenu du produit numerique")
        self.product.save()

        order = GuestProductOrder.objects.create(
            first_name='Test', last_name='Acheteur', email='buyer-dl@test.com',
            product=self.product, quantity=1,
            unit_price=self.product.price, subtotal=self.product.price, total=self.product.price,
            delivery_method='download', status=GuestProductOrder.Status.PAID,
        )
        self.link = GuestDownloadLink.objects.create(
            order=order, product=self.product,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_acheteur_peut_telecharger(self):
        response = Client().get(reverse('store:guest_download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 200)

    def test_token_inconnu_refuse(self):
        import uuid
        response = Client().get(reverse('store:guest_download', kwargs={'token': uuid.uuid4()}))
        self.assertEqual(response.status_code, 404)

    def test_lien_expire_refuse(self):
        self.link.expires_at = timezone.now() - timedelta(days=1)
        self.link.save()
        response = Client().get(reverse('store:guest_download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 200)  # page "lien expiré", pas le fichier
        self.assertTemplateUsed(response, 'store/download_expired.html')

    def test_limite_de_telechargements_atteinte_refuse(self):
        self.link.download_count = self.link.max_downloads
        self.link.save()
        response = Client().get(reverse('store:guest_download', kwargs={'token': self.link.token}))
        self.assertEqual(response.status_code, 200)  # page "limite atteinte", pas le fichier
        self.assertTemplateUsed(response, 'store/download_expired.html')

