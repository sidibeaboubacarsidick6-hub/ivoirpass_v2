"""
Tests des vues billetterie — apps/tickets/views.py
"""
import json
import hashlib
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Category, Event, TicketType
from apps.payments.models import Payment
from apps.tickets.models import (
    GuestOrder, GuestOrderItem, GuestTicket, Ticket,
)


def _setup_event(organizer=None, suffix='', event_type='physical', status='published'):
    if organizer is None:
        organizer = CustomUser.objects.create_user(
            email=f'org{suffix}@test.com', password='pass',
            first_name='Org', last_name='Test',
        )
        organizer.role = CustomUser.Role.ORGANIZER
        organizer.is_organizer_verified = True
        organizer.save()

    cat, _ = Category.objects.get_or_create(
        slug=f'cat{suffix}', defaults={'name': f'Cat{suffix}'},
    )
    now = timezone.now()
    event = Event.objects.create(
        title=f'Event{suffix}',
        slug=f'event{suffix}',
        description='d',
        short_description='0700000000',
        category=cat,
        organizer=organizer,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=31),
        status=status,
        event_type=event_type,
        commission_rate=Decimal('8.00'),
    )
    tt = TicketType.objects.create(
        event=event, name='Standard',
        price=Decimal('10000'), quantity=100, max_per_order=5,
        is_visible=True,
    )
    return event, tt


class SimpleRedirectTests(TestCase):
    def test_cart_redirect(self):
        response = self.client.get(reverse('tickets:cart'))
        self.assertEqual(response.status_code, 302)

    def test_order_confirmation_redirect(self):
        response = self.client.get(
            reverse('tickets:confirmation', kwargs={'order_number': 'IP-2026-XYZ'})
        )
        self.assertEqual(response.status_code, 302)


class GuestCheckoutTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-co')

    def _url(self):
        return reverse('tickets:guest_checkout', kwargs={'slug': self.event.slug})

    def test_get_affiche_formulaire(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn('event', response.context)
        self.assertIn('ticket_types', response.context)

    def test_event_non_publie_404(self):
        self.event.status = Event.Status.DRAFT
        self.event.save(update_fields=['status'])
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 404)

    def test_post_succes_cree_commande(self):
        data = {
            'first_name': 'Ali',
            'last_name': 'B',
            'email': 'ali@test.com',
            'phone': '+2250700000000',
            f'quantity_{self.tt.pk}': 2,
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)

        order = GuestOrder.objects.filter(email='ali@test.com').first()
        self.assertIsNotNone(order)
        self.assertEqual(order.subtotal, Decimal('20000'))
        self.assertEqual(order.guest_items.count(), 1)

        self.tt.refresh_from_db()
        self.assertEqual(self.tt.quantity_sold, 2)

    def test_post_sans_nom_rejette(self):
        data = {
            'first_name': '',
            'last_name': 'B',
            'email': 'ali@test.com',
            f'quantity_{self.tt.pk}': 1,
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GuestOrder.objects.filter(email='ali@test.com').exists())

    def test_post_panier_vide_rejette(self):
        data = {
            'first_name': 'Ali',
            'last_name': 'B',
            'email': 'ali@test.com',
            f'quantity_{self.tt.pk}': 0,
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GuestOrder.objects.filter(email='ali@test.com').exists())

    def test_post_stock_insuffisant_rejette(self):
        self.tt.quantity = 1
        self.tt.quantity_sold = 1
        self.tt.save()

        data = {
            'first_name': 'Ali',
            'last_name': 'B',
            'email': 'ali@test.com',
            f'quantity_{self.tt.pk}': 1,
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GuestOrder.objects.filter(email='ali@test.com').exists())


@override_settings(
    PAYDUNYA_MASTER_KEY='mk_test',
    PAYDUNYA_PRIVATE_KEY='pk_test',
    PAYDUNYA_TOKEN='tok_test',
    PAYDUNYA_API_BASE='https://api.paydunya.com/sandbox-api/v1',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
)
class GuestPaymentInitiateTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-pi')
        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com', phone='+2250700000000',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

    def _url(self):
        return reverse(
            'tickets:guest_payment',
            kwargs={'access_token': str(self.order.access_token)},
        )

    def test_commande_deja_payee_redirige_confirmation(self):
        self.order.status = GuestOrder.Status.PAID
        self.order.save(update_fields=['status'])

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('confirmation', response.url)

    @patch('requests.post')
    def test_paiement_initie_succes(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '00',
            'token': 'inv_tok_1',
            'response_text': 'https://paydunya.com/checkout/inv_tok_1',
        }
        mock_post.return_value = mock_resp

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('paydunya', response.url)

        payment = Payment.objects.filter(guest_order=self.order).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.paydunya_token, 'inv_tok_1')

    @patch('requests.post')
    def test_paiement_initie_erreur(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            'response_code': '100',
            'response_text': 'Erreur interne',
        }
        mock_post.return_value = mock_resp

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)

        payment = Payment.objects.filter(guest_order=self.order).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, Payment.Status.FAILED)


class GuestPaymentReturnTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-pr')
        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com', phone='+2250700000000',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
            payment_reference='tok_ret_1',
        )
        GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

    def _url(self):
        # ✅ FIX : URL réelle = guest_return
        return reverse(
            'tickets:guest_return',
            kwargs={'access_token': str(self.order.access_token)},
        )

    def test_deja_payee_redirige(self):
        self.order.status = GuestOrder.Status.PAID
        self.order.save(update_fields=['status'])
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_verify_completed_confirme_commande(self, mock_verify):
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, GuestOrder.Status.PAID)

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_verify_pending_ne_confirme_pas(self, mock_verify):
        mock_verify.return_value = {
            'success': True, 'status': 'pending', 'data': {},
        }
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, GuestOrder.Status.PENDING)


class GuestConfirmationTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-cf')
        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PAID,
        )
        GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

    def test_page_affichee(self):
        url = reverse(
            'tickets:guest_confirmation',
            kwargs={'access_token': str(self.order.access_token)},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['order'], self.order)

    def test_token_invalide_404(self):
        url = reverse(
            'tickets:guest_confirmation',
            kwargs={'access_token': '00000000-0000-0000-0000-000000000000'},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class GuestPaymentCancelTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-pc')
        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

    def _url(self):
        # ✅ FIX : URL réelle = guest_cancel
        return reverse(
            'tickets:guest_cancel',
            kwargs={'access_token': str(self.order.access_token)},
        )

    def test_annulation_marque_cancelled(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, GuestOrder.Status.CANCELLED)
        self.assertIsNotNone(self.order.payment_cancelled_at)

    def test_annulation_si_deja_payee_ne_fait_rien(self):
        self.order.status = GuestOrder.Status.PAID
        self.order.save(update_fields=['status'])
        self.client.get(self._url())
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, GuestOrder.Status.PAID)


@override_settings(PAYDUNYA_MASTER_KEY='mk_test')
class GuestWebhookTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-wh')
        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        self.url = reverse('tickets:guest_webhook')

    def _signature(self):
        return hashlib.sha512('mk_test'.encode()).hexdigest()

    def test_signature_invalide_403(self):
        response = self.client.post(
            self.url,
            data=json.dumps({'hash': 'faux'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_webhook_completed_confirme(self, mock_verify):
        mock_verify.return_value = {
            'success': True, 'status': 'completed', 'data': {},
        }
        payload = {
            'hash': self._signature(),
            'data': {
                'custom_data': {'guest_order_number': self.order.order_number},
                'invoice': {'status': 'completed'},
                'invoiceToken': 'tok_wh_1',
            },
        }
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, GuestOrder.Status.PAID)


class DownloadGuestTicketPdfTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(suffix='-dl')
        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PAID,
        )
        item = GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        item.generate_tickets()
        self.ticket = GuestTicket.objects.filter(order_item=item).first()

    @patch('apps.tickets.utils.generate_guest_ticket_pdf')
    def test_pdf_genere(self, mock_pdf):
        mock_pdf.return_value = b'%PDF-1.4 fake content'
        # ✅ FIX : URL réelle = guest_download_pdf
        url = reverse(
            'tickets:guest_download_pdf',
            kwargs={'access_token': str(self.ticket.access_token)},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_token_invalide_404(self):
        url = reverse(
            'tickets:guest_download_pdf',
            kwargs={'access_token': '00000000-0000-0000-0000-000000000000'},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class OnlineAccessRedirectTests(TestCase):
    def setUp(self):
        self.event, self.tt = _setup_event(
            suffix='-on', event_type='online',
        )
        self.event.online_link = 'https://zoom.us/j/test'
        self.event.save(update_fields=['online_link'])

        self.order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PAID,
        )
        item = GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        item.generate_tickets()
        self.ticket = GuestTicket.objects.filter(order_item=item).first()

    def _url(self):
        return reverse(
            'tickets:online_access',
            kwargs={'token': self.ticket.online_access_token},
        )

    def test_acces_ok(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)

    def test_billet_void_refuse(self):
        self.ticket.status = GuestTicket.Status.VOID
        self.ticket.save(update_fields=['status'])
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn('reason', response.context)