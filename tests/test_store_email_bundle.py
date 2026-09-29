"""
Tests du fix mail bundle boutique (2026-09-29).

Bug corrigé : `guest_store_order_confirmed` utilisait `product.is_digital`
qui est TOUJOURS True pour un BUNDLE → un acheteur qui prenait uniquement
le physique recevait un mail "téléchargements prêts" sans aucun lien.

Fix : décision basée sur `order.delivery_method`.
"""
from decimal import Decimal

from django.core.mail import EmailMultiAlternatives
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.store.models import (
    Product, ProductCategory, GuestProductOrder, GuestDownloadLink,
)
from apps.notifications.service import NotificationService


def _make_seller(email='s@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='S', last_name='T',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_product(seller, product_type='bundle'):
    cat, _ = ProductCategory.objects.get_or_create(name='Test')
    return Product.objects.create(
        name='Livre+Album', description='d',
        product_type=product_type, price=5000,
        price_physical=3000, price_digital=2500,
        seller=seller, category=cat,
        status=Product.Status.PUBLISHED,
        stock=10,
    )


def _make_order(product, delivery_method):
    return GuestProductOrder.objects.create(
        first_name='Jean', last_name='A',
        email='buyer@test.com',
        product=product, quantity=1,
        unit_price=product.price, subtotal=product.price, total=product.price,
        delivery_method=delivery_method,
        status=GuestProductOrder.Status.PAID,
        paid_at=timezone.now(),
    )


class StoreEmailBundleTests(TestCase):
    """
    Vérifie la bonne sélection du template email selon le delivery_method
    choisi (pas selon product.is_digital).
    """

    def setUp(self):
        self.seller = _make_seller()
        self.bundle = _make_product(self.seller, product_type='bundle')

        # Intercepter les envois
        self.sent = []
        original = EmailMultiAlternatives.send
        sent = self.sent
        def fake_send(self):
            sent.append({
                'subject': self.subject,
                'alternatives': [(c, m) for c, m in self.alternatives],
            })
            return 1
        EmailMultiAlternatives.send = fake_send
        self._original_send = original

    def tearDown(self):
        EmailMultiAlternatives.send = self._original_send

    def _get_html(self):
        self.assertEqual(len(self.sent), 1, "Un seul email attendu")
        return next(
            (c for c, m in self.sent[0]['alternatives'] if m == 'text/html'),
            None,
        )

    def test_bundle_physical_only_recoit_mail_physique_sans_liens(self):
        order = _make_order(self.bundle, 'delivery')
        # Pas de liens de téléchargement (l'acheteur a pris le physique)
        NotificationService.guest_store_order_confirmed(order)

        html = self._get_html()
        self.assertIn('Commande confirmée', html)
        self.assertNotIn('téléchargements sont prêts', html.lower())
        self.assertNotIn('version numérique', html)

    def test_bundle_both_recoit_mail_physique_avec_section_numerique(self):
        order = _make_order(self.bundle, 'both')
        # On simule un lien (comme mark_as_paid en génère un)
        link = GuestDownloadLink.objects.create(
            order=order, product=self.bundle,
            max_downloads=3,
            expires_at=timezone.now() + timezone.timedelta(hours=48),
        )
        NotificationService.guest_store_order_confirmed(order)

        html = self._get_html()
        self.assertIn('Commande confirmée', html)
        self.assertIn('version numérique', html)
        self.assertIn(str(link.token), html)

    def test_bundle_download_only_recoit_mail_digital(self):
        order = _make_order(self.bundle, 'download')
        GuestDownloadLink.objects.create(
            order=order, product=self.bundle,
            max_downloads=3,
            expires_at=timezone.now() + timezone.timedelta(hours=48),
        )
        NotificationService.guest_store_order_confirmed(order)

        html = self._get_html()
        self.assertIn('téléchargements sont prêts', html.lower())
        self.assertNotIn('Commande confirmée !', html)  # pas le titre physique

    def test_produit_physique_pur_recoit_mail_physique(self):
        physical = _make_product(self.seller, product_type='physical')
        order = _make_order(physical, 'delivery')
        NotificationService.guest_store_order_confirmed(order)

        html = self._get_html()
        self.assertIn('Commande confirmée', html)
        self.assertNotIn('version numérique', html)