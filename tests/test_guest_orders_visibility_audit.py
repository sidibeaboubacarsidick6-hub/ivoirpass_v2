"""
Test d'audit — Visibilité des commandes invité dans le back-office Django
et dans les rapports/exports plateforme.

Contexte : l'achat "avec compte" (Order/ProductOrder) n'est pas le parcours
réellement utilisé côté site (la boutique en particulier ne vend qu'en achat
invité) — sans ces correctifs, les pages admin "Commandes"/"Tickets" et les
rapports BCEAO/exports admin apparaissaient vides ou très incomplets alors
que l'activité réelle a bien lieu sous GuestOrder/GuestProductOrder.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_guest_orders_visibility_audit -v 2
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.tickets.models import GuestOrder
from apps.store.models import Product, ProductCategory, GuestProductOrder
from apps.dashboard.admin import bceao_report_view


class GuestOrderAdminRegistrationTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(email='superadmin@test.com', password='Pass123!')
        self.admin.role = CustomUser.Role.ADMIN
        self.admin.save()
        self.client_ = Client()
        self.client_.login(email='superadmin@test.com', password='Pass123!')

    def test_guestorder_changelist_accessible_et_liste_les_commandes(self):
        order = GuestOrder.objects.create(
            first_name='Ache', last_name='Teur', email='guest@test.com',
            subtotal=Decimal('5000'), total=Decimal('5000'), status=GuestOrder.Status.PAID,
        )
        response = self.client_.get(reverse('admin:tickets_guestorder_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)

    def test_guestticket_changelist_accessible(self):
        response = self.client_.get(reverse('admin:tickets_guestticket_changelist'))
        self.assertEqual(response.status_code, 200)

    def test_guestproductorder_changelist_accessible_et_liste_les_commandes(self):
        category = ProductCategory.objects.create(name='Cat', slug='cat')
        product = Product.objects.create(
            name='Produit test', slug='produit-test', category=category,
            seller=self.admin, price=Decimal('2000'), commission_rate=Decimal('10'),
        )
        order = GuestProductOrder.objects.create(
            first_name='Ache', last_name='Teur', email='guest2@test.com',
            product=product, quantity=1, unit_price=Decimal('2000'),
            subtotal=Decimal('2000'), total=Decimal('2000'), status=GuestProductOrder.Status.PAID,
        )
        response = self.client_.get(reverse('admin:store_guestproductorder_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_number)


class BceaoReportGuestCoverageTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(email='rep@test.com', password='Pass123!')
        self.admin.role = CustomUser.Role.ADMIN
        self.admin.save()
        self.client_ = Client()
        self.client_.login(email='rep@test.com', password='Pass123!')

    def test_rapport_bceao_compte_les_commandes_invite(self):
        GuestOrder.objects.create(
            first_name='A', last_name='B', email='g1@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PAID, paid_at=timezone.now(),
        )
        response = self.client_.get(reverse('bceao-report'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['ticket_orders_guest'], 1)
        self.assertEqual(response.context['ticket_volume'], 10000)


class AdminExportsGuestCoverageTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(email='exp@test.com', password='Pass123!')
        self.admin.role = CustomUser.Role.ADMIN
        self.admin.save()
        self.client_ = Client()
        self.client_.login(email='exp@test.com', password='Pass123!')
        self.order = GuestOrder.objects.create(
            first_name='Guest', last_name='Buyer', email='exportguest@test.com',
            subtotal=Decimal('7500'), total=Decimal('7500'), status=GuestOrder.Status.PAID,
        )

    def test_export_csv_contient_la_commande_invite(self):
        response = self.client_.get(reverse('admin_export_csv'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        self.assertIn(self.order.order_number, content)
        self.assertIn('Invité', content)

    def test_export_excel_repond_200(self):
        response = self.client_.get(reverse('admin_export_excel'))
        self.assertEqual(response.status_code, 200)
