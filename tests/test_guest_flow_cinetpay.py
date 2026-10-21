"""
Tests du flux guest avec CinetPay (provider actif via override_settings).
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
        status=Event.Status.PUBLISHED, commission_rate=Decimal('8.00'),
    )
    tt = TicketType.objects.create(event=ev, name='Std', price=Decimal('5000'), quantity=100)
    order = GuestOrder.objects.create(
        first_name='B', last_name='E', email='b@t.com',
        phone='+2250700000000', total=Decimal('5000'), status=GuestOrder.Status.PENDING,
    )
    GuestOrderItem.objects.create(order=order, ticket_type=tt, quantity=1, unit_price=Decimal('5000'))
    return order


@override_settings(
    PAYMENT_PROVIDER='cinetpay',
    CINETPAY_API_KEY='test_key', CINETPAY_SITE_ID='test_site',
    CINETPAY_API_BASE='https://api-checkout.cinetpay.com/v2',
    PAYDUNYA_BASE_URL='https://ivoirpass.test',
)
class CinetPayGuestFlowTests(TestCase):

    @patch('apps.payments.cinetpay.requests.post')
    def test_initiate_creates_payment_with_cinetpay(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {
                'code': '201',
                'data': {'payment_url': 'https://secure.cinetpay.com/xyz', 'payment_token': 'token_123'}
            },
        )
        order = _make_order()
        response = self.client.get(f'/billets/guest/payer/{order.access_token}/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('secure.cinetpay.com', response.url)

        payment = Payment.objects.get(guest_order=order)
        self.assertEqual(payment.provider, 'cinetpay')
        self.assertEqual(payment.provider_reference, 'token_123')


    @patch('apps.payments.cinetpay.CinetPayService.verify_webhook_signature', return_value=True)
    @patch('apps.payments.cinetpay.requests.post')
    def test_webhook_confirms_order(self, mock_post, mock_verify_sig):
        mock_post.side_effect = [
            MagicMock(status_code=201, json=lambda: {'code': '201', 'data': {'payment_url': 'https://x', 'payment_token': 'token_123'}}),
            MagicMock(status_code=200, json=lambda: {'code': '00', 'data': {'status': 'ACCEPTED', 'amount': 5000}}),
        ]
        order = _make_order()
        self.client.get(f'/billets/guest/payer/{order.access_token}/')

        # ⚠️ Envoyer une vraie string URL-encoded (comme CinetPay en prod),
        # pas un dict (que Django encode bizarrement dans certains cas).
        from urllib.parse import urlencode
        payload = urlencode({
            'cpm_trans_id': 'token_123',
            'cpm_result': '00',
            'cpm_trans_status': 'ACCEPTED',
            'cpm_custom': order.order_number,
        })
        resp = self.client.post(
            '/billets/guest/webhook/',
            data=payload,
            content_type='application/x-www-form-urlencoded',
        )
        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.PAID)
