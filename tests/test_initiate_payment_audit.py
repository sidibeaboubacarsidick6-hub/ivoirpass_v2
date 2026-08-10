from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem
from django.utils import timezone
from datetime import timedelta

class InitiatePaymentFixedTest(TestCase):
    def setUp(self):
        self.buyer = CustomUser.objects.create_user(email='buyer-fix@t.com', password='Pass123!')
        organizer = CustomUser.objects.create_user(email='orga-fix@t.com', password='Pass123!', role='organizer', is_organizer_verified=True)
        category = Category.objects.create(name='Concert Fix', slug='concert-fix')
        event = Event.objects.create(
            title='Concert Fix', description='Test', category=category, organizer=organizer,
            start_date=timezone.now() + timedelta(days=10), end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        ticket_type = TicketType.objects.create(event=event, name='Standard', price=5000, quantity=100)
        self.order = Order.objects.create(buyer=self.buyer, subtotal=5000, total=5000, status='pending')
        OrderItem.objects.create(order=self.order, ticket_type=ticket_type, quantity=1, unit_price=5000)

    @patch('apps.payments.paydunya.requests.post')
    def test_initiate_payment_ne_plante_plus_et_redirige(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'token': 'fake_token_123',
            'response_text': 'https://paydunya.com/checkout/fake_token_123',
        }
        mock_post.return_value = mock_response

        client = Client()
        client.force_login(self.buyer)
        response = client.get(reverse('payments:initiate', kwargs={'order_number': self.order.order_number}))
        print("\nStatus:", response.status_code)
        print("Redirect vers:", response.get('Location'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://paydunya.com/checkout/fake_token_123')

        # Vérifie que le payload envoyé à PayDunya contient bien le bon article
        call_kwargs = mock_post.call_args.kwargs
        print("Items envoyés à PayDunya:", call_kwargs['json']['invoice']['items'])
        self.assertIn('item_1', call_kwargs['json']['invoice']['items'])
        self.assertEqual(call_kwargs['json']['invoice']['total_amount'], '5000')