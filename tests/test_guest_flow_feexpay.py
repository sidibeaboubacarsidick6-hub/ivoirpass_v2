"""
Tests du flux guest avec FeexPay (provider actif via override_settings).
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import Category, Event, TicketType
from apps.tickets.models import GuestOrder, GuestOrderItem
from apps.payments.models import Payment


User = get_user_model()


def _make_order():
    org = User.objects.create_user(
        email='o@t.com', password='x', first_name='O', last_name='A',
        role=User.Role.ORGANIZER,
    )
    cat = Category.objects.create(name='C', slug='c')
    now = timezone.now()
    ev = Event.objects.create(
        title='E', slug='e', description='d', short_description='0700',
        category=cat, organizer=org,
        start_date=now + timedelta(days=30),
        end_date=now + timedelta(days=31),
        status=Event.Status.PUBLISHED,
        commission_rate=Decimal('8.00'),
    )
    tt = TicketType.objects.create(
        event=ev, name='Std', price=Decimal('5000'), quantity=100,
    )
    order = GuestOrder.objects.create(
        first_name='B', last_name='E', email='b@t.com',
        phone='+2250700000000', total=Decimal('5000'),
        status=GuestOrder.Status.PENDING,
    )
    GuestOrderItem.objects.create(
        order=order, ticket_type=tt, quantity=1, unit_price=Decimal('5000'),
    )
    return order


@override_settings(
    PAYMENT_PROVIDER='feexpay',
    FEEXPAY_API_TOKEN='fp_test', FEEXPAY_SHOP_ID='shop',
    FEEXPAY_BASE_URL='https://api-sandbox.feexpay.me',
    PAYDUNYA_BASE_URL='https://ivoirpass.test',
)
class FeexPayGuestFlowTests(TestCase):

    @patch('apps.payments.feexpay.requests.post')
    def test_initiate_creates_payment_with_feexpay_provider(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'reference': 'REF1', 'status': 'PENDING',
                          'payment_url': 'https://sandbox-wave.example.com/pay/REF1'},
        )
        order = _make_order()
        self.client.get(f'/billets/guest/payer/{order.access_token}/')
        payment = Payment.objects.get(guest_order=order)
        self.assertEqual(payment.provider, 'feexpay')
        self.assertEqual(payment.provider_reference, 'REF1')

    @patch('apps.payments.feexpay.requests.get')
    @patch('apps.payments.feexpay.requests.post')
    def test_webhook_confirms_order(self, mock_post, mock_get):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'reference': 'REF1', 'status': 'PENDING',
                          'payment_url': 'https://x'},
        )
        order = _make_order()
        self.client.get(f'/billets/guest/payer/{order.access_token}/')
        # Payment existe avec provider=feexpay, order PENDING
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {'reference': 'REF1', 'status': 'SUCCESSFUL',
                          'amount': 5000},
        )
        import json
        resp = self.client.post(
            '/billets/guest/webhook/',
            data=json.dumps({
                'reference': 'REF1', 'status': 'SUCCESSFUL',
                'amount': 5000, 'callback_info': order.order_number,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.PAID)

    @patch('apps.payments.feexpay.requests.get')
    @patch('apps.payments.feexpay.requests.post')
    def test_webhook_provider_mismatch_rejects(self, mock_post, mock_get):
        # Créer Payment avec provider=paydunya (simulate switch)
        order = _make_order()
        Payment.objects.create(
            guest_order=order, amount=order.total,
            provider='paydunya', provider_reference='OTHER',
        )
        import json
        resp = self.client.post(
            '/billets/guest/webhook/',
            data=json.dumps({
                'reference': 'REF1', 'status': 'SUCCESSFUL',
                'amount': 5000, 'callback_info': order.order_number,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.PENDING)

    def test_missing_phone_fails(self):
        order = _make_order()
        order.phone = ''  # Numéro manquant
        order.save()
        
        response = self.client.get(f'/billets/guest/payer/{order.access_token}/')
        # Doit rediriger vers la page de détail avec un message d'erreur
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(guest_order=order)
        self.assertEqual(payment.status, Payment.Status.FAILED)