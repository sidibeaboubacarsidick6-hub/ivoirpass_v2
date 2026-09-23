"""
Test d'audit — Admin Payment plantait en 500 sur un paiement boutique.

L'extension du modèle Payment à la boutique (product_order/guest_product_order)
n'avait pas été répercutée dans apps/payments/admin.py : la méthode
`commande()` ne connaissait que order/guest_order et plantait
(AttributeError) dès qu'un paiement boutique apparaissait dans la liste.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_payments_admin_store_audit -v 2
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.store.models import ProductCategory, Product, GuestProductOrder
from apps.payments.models import Payment


class PaymentAdminStorePaymentTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(email='admin.payadmin@test.com', password='Pass123!')
        self.admin.role = CustomUser.Role.ADMIN
        self.admin.save()
        self.client_ = Client()
        self.client_.login(email='admin.payadmin@test.com', password='Pass123!')

        seller = CustomUser.objects.create_user(email='seller.payadmin@test.com', password='Pass123!', role='organizer')
        category = ProductCategory.objects.create(name='Cat PayAdmin', slug='cat-payadmin')
        product = Product.objects.create(
            name='Produit PayAdmin', slug='produit-payadmin', category=category, seller=seller,
            product_type=Product.ProductType.DIGITAL, price=Decimal('1000'), commission_rate=Decimal('10'),
            status=Product.Status.PUBLISHED,
        )
        order = GuestProductOrder.objects.create(
            first_name='A', last_name='B', email='buyer.payadmin@test.com',
            product=product, quantity=1, unit_price=Decimal('1000'),
            subtotal=Decimal('1000'), total=Decimal('1000'), status=GuestProductOrder.Status.PAID,
        )
        Payment.objects.create(
            guest_product_order=order, amount=Decimal('1000'), currency='XOF',
            status=Payment.Status.COMPLETED, provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_payadmin',
        )
        self.order_number = order.order_number

    def test_liste_admin_payment_ne_plante_pas_avec_un_paiement_boutique(self):
        response = self.client_.get(reverse('admin:payments_payment_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order_number)
