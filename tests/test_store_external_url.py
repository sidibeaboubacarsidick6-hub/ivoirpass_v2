"""
IvoirPass V2 — Tests étape 2 : lien externe + compteur de clics boutique.

Couvre les cas #4, #5, #6 du chantier :
  #4 - Produit digital avec external_url seul → publiable (form OK)
  #5 - Produit digital sans fichier ni URL → form bloqué
  #6 - Achat produit external_url → /guest/telecharger/<token>/
       redirige vers external_url + compteur incrémenté
       + limite de download NON consommée
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import CustomUser
from apps.store.models import (
    Product,
    ProductCategory,
    GuestProductOrder,
    GuestDownloadLink,
)
from apps.store.forms import ProductForm


# ============================================================
# Helpers
# ============================================================

def _make_seller(email='seller@test.com'):
    return CustomUser.objects.create_user(
        email=email,
        password='testpass123',
        first_name='Vendeur',
        last_name='Test',
    )


def _make_category(name='Musique'):
    return ProductCategory.objects.create(name=name)


def _make_product(seller, category, **kwargs):
    """Crée un produit digital minimal, surchargeable via kwargs."""
    defaults = {
        'name': 'Album Test',
        'description': 'Description test',
        'product_type': Product.ProductType.DIGITAL,
        'price': 2000,
        'status': Product.Status.PUBLISHED,
        'seller': seller,
        'category': category,
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def _make_order_and_link(product):
    """Crée une GuestProductOrder PAID + un GuestDownloadLink valide."""
    order = GuestProductOrder.objects.create(
        first_name='Jean',
        last_name='Acheteur',
        email='acheteur@test.com',
        product=product,
        quantity=1,
        unit_price=product.price,
        subtotal=product.price,
        total=product.price,
        status=GuestProductOrder.Status.PAID,
        paid_at=timezone.now(),
    )
    link = GuestDownloadLink.objects.create(
        order=order,
        product=product,
        max_downloads=3,
        expires_at=timezone.now() + timedelta(hours=48),
    )
    return order, link


# ============================================================
# TEST #4 — Produit digital avec external_url seul → publiable
# ============================================================

class ProductFormExternalUrlOnlyTests(TestCase):
    """Cas #4 : produit digital sans fichier mais avec URL → form valide."""

    def setUp(self):
        self.seller = _make_seller()
        self.category = _make_category()

    def _base_form_data(self, **overrides):
        data = {
            'name': 'Album Numérique',
            'description': 'Description test',
            'category': self.category.pk,
            'product_type': Product.ProductType.DIGITAL,
            'price': 2000,
            'stock': 0,
            'status': Product.Status.PUBLISHED,
        }
        data.update(overrides)
        return data

    def test_digital_with_external_url_only_is_valid(self):
        form = ProductForm(
            data=self._base_form_data(
                external_url='https://open.spotify.com/album/abc123',
            )
        )
        self.assertTrue(
            form.is_valid(),
            f"Form devrait être valide mais erreurs : {form.errors.as_json()}"
        )
        self.assertEqual(
            form.cleaned_data['external_url'],
            'https://open.spotify.com/album/abc123',
        )

    def test_bundle_with_external_url_only_is_valid(self):
        """Un bundle peut aussi vendre uniquement via URL externe."""
        form = ProductForm(
            data=self._base_form_data(
                product_type=Product.ProductType.BUNDLE,
                external_url='https://bandcamp.com/album/xyz',
                price_physical=3000,
                price_digital=1500,
            )
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())


# ============================================================
# TEST #5 — Produit digital sans fichier NI URL → form bloqué
# ============================================================

class ProductFormMissingDigitalContentTests(TestCase):
    """Cas #5 : produit digital sans fichier et sans URL → rejeté."""

    def setUp(self):
        self.seller = _make_seller()
        self.category = _make_category()

    def _base_form_data(self, **overrides):
        data = {
            'name': 'Produit Test',
            'description': 'Description test',
            'category': self.category.pk,
            'price': 2000,
            'stock': 0,
            'status': Product.Status.PUBLISHED,
        }
        data.update(overrides)
        return data

    def test_digital_without_file_and_without_url_is_rejected(self):
        form = ProductForm(data=self._base_form_data(
            product_type=Product.ProductType.DIGITAL,
            # ni digital_file ni external_url
        ))
        self.assertFalse(form.is_valid())
        errors_str = str(form.errors).lower()
        self.assertTrue(
            'fichier' in errors_str or 'lien externe' in errors_str,
            f"Message d'erreur attendu sur fichier/URL, reçu : {form.errors}",
        )

    def test_bundle_without_file_and_without_url_is_rejected(self):
        form = ProductForm(data=self._base_form_data(
            product_type=Product.ProductType.BUNDLE,
            price_physical=3000,
            price_digital=1500,
            stock=5,
        ))
        self.assertFalse(form.is_valid())

    def test_physical_without_file_and_url_is_valid(self):
        """Un produit purement PHYSICAL n'a pas besoin de contenu numérique."""
        form = ProductForm(data=self._base_form_data(
            product_type=Product.ProductType.PHYSICAL,
            price=5000,
            stock=10,
        ))
        self.assertTrue(
            form.is_valid(),
            f"Produit physique sans contenu numérique devrait être OK : "
            f"{form.errors.as_json()}",
        )


# ============================================================
# TEST #6 — Achat avec external_url → redirection + compteur
# ============================================================

class GuestDownloadExternalUrlRedirectTests(TestCase):
    """Cas #6 : /guest/telecharger/<token>/ redirige vers external_url."""

    def setUp(self):
        self.client = Client()
        self.seller = _make_seller()
        self.category = _make_category()
        self.product = _make_product(
            self.seller,
            self.category,
            external_url='https://open.spotify.com/album/external-test',
        )
        self.order, self.link = _make_order_and_link(self.product)

    def test_redirect_to_external_url_and_increment_counter(self):
        url = reverse('store:guest_download', kwargs={'token': self.link.token})

        # Premier clic
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            'https://open.spotify.com/album/external-test',
        )

        self.link.refresh_from_db()
        self.assertEqual(self.link.external_click_count, 1)
        # ⚠️ La limite de download ne doit PAS être consommée (Q11)
        self.assertEqual(self.link.download_count, 0)

        # Deuxième clic — le compteur s'incrémente encore
        self.client.get(url)
        self.link.refresh_from_db()
        self.assertEqual(self.link.external_click_count, 2)
        self.assertEqual(self.link.download_count, 0)

    def test_external_url_priority_over_digital_file(self):
        """
        Si les deux sont renseignés, external_url est prioritaire (Q8)
        — même si un digital_file existe.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.product.digital_file = SimpleUploadedFile(
            'fake.pdf', b'%PDF-1.4 fake', content_type='application/pdf'
        )
        self.product.save()

        url = reverse('store:guest_download', kwargs={'token': self.link.token})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.product.external_url)
        self.link.refresh_from_db()
        self.assertEqual(self.link.external_click_count, 1)
        self.assertEqual(self.link.download_count, 0)

    def test_expired_link_still_blocked_for_external_url(self):
        """Même pour un lien externe, un lien expiré reste refusé."""
        self.link.expires_at = timezone.now() - timedelta(hours=1)
        self.link.save(update_fields=['expires_at'])

        url = reverse('store:guest_download', kwargs={'token': self.link.token})
        response = self.client.get(url)

        # Vue affiche download_expired.html (200) et ne redirige pas
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'store/download_expired.html',
            [t.name for t in response.templates],
            f"Template attendu store/download_expired.html. "
            f"Templates utilisés : {[t.name for t in response.templates]}",
        )
        # Compteur non incrémenté
        self.link.refresh_from_db()
        self.assertEqual(self.link.external_click_count, 0)