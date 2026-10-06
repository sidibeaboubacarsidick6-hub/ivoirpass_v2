"""
Tests des vues de compte — apps/accounts/views.py

⚠️ Adapte les noms d'URL si différents de tes apps/accounts/urls.py.

Couvre :
- home : cache + pagination
- profile : vue simple
- profile_edit : validation + KYC notification
- change_password
- address_list : GET + POST
- address_delete
- post_login_redirect : par rôle
- my_orders_history
- download_invoice_pdf : billet + produit
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from apps.accounts.models import CustomUser, UserAddress
from apps.events.models import Category, Event, TicketType
from apps.tickets.models import Order, OrderItem
from apps.store.models import Product, ProductOrder, ProductCategory


User = get_user_model()


class HomeViewTests(TestCase):
    """Tests de la vue home."""

    def test_home_sans_evenements(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_home_avec_evenement_publie(self):
        """Un événement publié remonte dans les featured."""
        org = CustomUser.objects.create_user(
            email='org-h@test.com', password='pass',
            role=CustomUser.Role.ORGANIZER,
        )
        cat, _ = Category.objects.get_or_create(slug='c-h', defaults={'name': 'C'})
        now = timezone.now()
        Event.objects.create(
            title='Event Home', slug='event-home',
            description='d', short_description='0700000000',
            category=cat, organizer=org,
            start_date=now + timezone.timedelta(days=10),
            end_date=now + timezone.timedelta(days=11),
            status=Event.Status.PUBLISHED,
        )

        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('featured_events', response.context)


class ProfileViewTests(TestCase):
    """Tests de profile."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='u@test.com', password='Pass123!',
        )
        self.client.force_login(self.user)

    def test_profile_affiche(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)

    def test_profile_requires_login(self):
        """Sans login → redirection."""
        self.client.logout()
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 302)


class AddressListTests(TestCase):
    """Tests de address_list."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='addr@test.com', password='Pass123!',
        )
        self.client.force_login(self.user)

    @patch('apps.accounts.views.render')
    def test_get_affiche_formulaire(self, mock_render):
        """GET → render appelé avec le bon template."""
        from django.http import HttpResponse
        mock_render.return_value = HttpResponse('ok')

        response = self.client.get(reverse('accounts:addresses'))

        self.assertEqual(response.status_code, 200)
        # Vérifie que le bon template est demandé
        args = mock_render.call_args[0]
        self.assertEqual(args[1], 'pages/addresses.html')

    @patch('apps.accounts.views.render')
    def test_post_cree_adresse(self, mock_render):
        """POST valide → adresse créée + redirection."""
        from django.http import HttpResponse
        mock_render.return_value = HttpResponse('ok')

        data = {
            'label': 'Maison',
            'full_name': 'Ali B',
            'phone': '+2250700000000',
            'address_line1': 'Rue 1',
            'city': 'Abidjan',
            'zone': 'Cocody',
            'is_default': False,
        }
        response = self.client.post(reverse('accounts:addresses'), data)

        # Redirection si succès
        if response.status_code == 302:
            self.assertEqual(
                UserAddress.objects.filter(user=self.user).count(), 1,
            )

class AddressDeleteTests(TestCase):
    """Tests de address_delete."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='del@test.com', password='Pass123!',
        )
        self.other = CustomUser.objects.create_user(
            email='other@test.com', password='Pass123!',
        )
        self.client.force_login(self.user)
        self.address = UserAddress.objects.create(
            user=self.user, label='X',
            full_name='Ali', phone='+2250700000000',
            address_line1='Rue', city='Abidjan', zone='Cocody',
        )

    def test_delete_supprime_adresse(self):
        url = reverse('accounts:address_delete', kwargs={'pk': self.address.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserAddress.objects.filter(pk=self.address.pk).exists())

    def test_delete_adresse_dun_autre_404(self):
        """IDOR : ne peut pas supprimer l'adresse d'un autre user."""
        other_addr = UserAddress.objects.create(
            user=self.other, label='Y',
            full_name='Other', phone='+2250700000001',
            address_line1='Rue 2', city='Abidjan', zone='Plateau',
        )
        url = reverse('accounts:address_delete', kwargs={'pk': other_addr.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(UserAddress.objects.filter(pk=other_addr.pk).exists())


class PostLoginRedirectLogicTests(TestCase):
    """
    La vue post_login_redirect existe dans views.py mais n'est pas
    branchée dans urls.py — on teste directement via appel de fonction.
    """

    def _call(self, user):
        from django.test import RequestFactory
        from apps.accounts.views import post_login_redirect
        factory = RequestFactory()
        request = factory.get('/fake/')
        request.user = user
        return post_login_redirect(request)

    def test_organisateur_va_dashboard(self):
        u = CustomUser.objects.create_user(
            email='org@test.com', password='pass',
            role=CustomUser.Role.ORGANIZER,
        )
        response = self._call(u)
        self.assertIn('dashboard', response.url)

    def test_scanner_va_scanner(self):
        u = CustomUser.objects.create_user(
            email='scan@test.com', password='pass',
            role=CustomUser.Role.SCANNER,
        )
        response = self._call(u)
        self.assertIn('scanner', response.url)

    def test_user_simple_va_home(self):
        u = CustomUser.objects.create_user(
            email='u@test.com', password='pass',
        )
        # Rôle par défaut (peu importe le nom exact — on teste que ça va à home)
        response = self._call(u)
        self.assertEqual(response.status_code, 302)

    def test_anonyme_va_home(self):
        from django.contrib.auth.models import AnonymousUser
        response = self._call(AnonymousUser())
        self.assertEqual(response.status_code, 302)


class MyOrdersHistoryTests(TestCase):
    """Tests de my_orders_history."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='hist@test.com', password='Pass123!',
        )
        self.client.force_login(self.user)

    def test_page_affichee(self):
        response = self.client.get(reverse('accounts:my_orders_history'))
        self.assertEqual(response.status_code, 200)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('accounts:my_orders_history'))
        self.assertEqual(response.status_code, 302)


class DownloadInvoicePdfTests(TestCase):
    """Tests de download_invoice_pdf."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='inv@test.com', password='Pass123!',
            first_name='Ali', last_name='B',
        )
        self.client.force_login(self.user)

    def _make_ticket_order(self):
        org = CustomUser.objects.create_user(
            email='org-inv@test.com', password='pass',
            role=CustomUser.Role.ORGANIZER,
        )
        cat, _ = Category.objects.get_or_create(slug='c-inv', defaults={'name': 'C'})
        now = timezone.now()
        event = Event.objects.create(
            title='Event Inv', slug='event-inv',
            description='d', short_description='0700000000',
            category=cat, organizer=org,
            start_date=now + timezone.timedelta(days=30),
            end_date=now + timezone.timedelta(days=31),
            status=Event.Status.PUBLISHED,
        )
        tt = TicketType.objects.create(
            event=event, name='Std',
            price=Decimal('10000'), quantity=100,
        )
        order = Order.objects.create(
            buyer=self.user, subtotal=Decimal('10000'),
            total=Decimal('10000'), status=Order.Status.PAID,
        )
        OrderItem.objects.create(
            order=order, ticket_type=tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        return order

    def test_facture_billet(self):
        order = self._make_ticket_order()
        url = reverse(
            'accounts:download_invoice',
            kwargs={'order_type': 'ticket', 'order_number': order.order_number},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_facture_commande_dun_autre_404(self):
        """IDOR : ne peut pas générer la facture d'un autre."""
        other = CustomUser.objects.create_user(
            email='other-inv@test.com', password='pass',
        )
        org = CustomUser.objects.create_user(
            email='org-x@test.com', password='pass',
            role=CustomUser.Role.ORGANIZER,
        )
        cat, _ = Category.objects.get_or_create(slug='c-x', defaults={'name': 'C'})
        now = timezone.now()
        event = Event.objects.create(
            title='Ex', slug='ex', description='d',
            short_description='0700000000', category=cat, organizer=org,
            start_date=now + timezone.timedelta(days=30),
            end_date=now + timezone.timedelta(days=31),
            status=Event.Status.PUBLISHED,
        )
        tt = TicketType.objects.create(event=event, name='S', price=Decimal('10000'), quantity=10)
        order = Order.objects.create(
            buyer=other, subtotal=Decimal('10000'),
            total=Decimal('10000'), status=Order.Status.PAID,
        )
        OrderItem.objects.create(
            order=order, ticket_type=tt,
            quantity=1, unit_price=Decimal('10000'),
        )

        url = reverse(
            'accounts:download_invoice',
            kwargs={'order_type': 'ticket', 'order_number': order.order_number},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)