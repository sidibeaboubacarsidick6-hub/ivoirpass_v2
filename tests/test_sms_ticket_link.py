"""
Tests du lien SMS vers les billets (/b/<access_token>/).
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Category, Event, TicketType
from apps.tickets.models import GuestOrder, GuestOrderItem


User = get_user_model()


class ShortTicketRedirectTests(TestCase):
    """Tests de la vue /b/<access_token>/."""

    def setUp(self):
        self.org = User.objects.create_user(
            email='org@test.com', password='test1234',
            first_name='Org', last_name='A',
            role=User.Role.ORGANIZER,
        )
        self.cat = Category.objects.create(name='Cat', slug='cat')
        now = timezone.now()
        self.event = Event.objects.create(
            title='E', slug='e', description='d',
            short_description='0700000000', category=self.cat,
            organizer=self.org,
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=31),
            status=Event.Status.PUBLISHED,
            commission_rate=Decimal('8.00'),
        )
        self.tt = TicketType.objects.create(
            event=self.event, name='Std',
            price=Decimal('5000'), quantity=100,
        )
        self.order = GuestOrder.objects.create(
            first_name='B', last_name='E',
            email='b@test.com', phone='+2250700000000',
            total=Decimal('5000'),
            status=GuestOrder.Status.PAID,
        )
        GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('5000'),
        )

    def test_short_url_redirects_to_confirmation(self):
        """GET /b/<token>/ → redirige vers la page de confirmation."""
        url = reverse('short_ticket', kwargs={'access_token': self.order.access_token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        expected = reverse(
            'tickets:guest_confirmation',
            kwargs={'access_token': self.order.access_token},
        )
        self.assertEqual(response.url, expected)

    def test_short_url_unknown_token_returns_404(self):
        """Token inconnu → 404 (Http404 levée par la vue)."""
        import uuid
        fake_token = uuid.uuid4()
        url = reverse('short_ticket', kwargs={'access_token': fake_token})
        response = self.client.get(url)
        # La vue lève Http404 si aucun GuestOrder/Order ne correspond
        self.assertEqual(response.status_code, 404)


class SMSWithLinkTests(TestCase):
    """Vérifie que les SMS contiennent le lien court."""

    def setUp(self):
        self.org = User.objects.create_user(
            email='org2@test.com', password='test1234',
            first_name='Org', last_name='B',
            role=User.Role.ORGANIZER,
        )
        self.cat = Category.objects.create(name='Cat2', slug='cat2')
        now = timezone.now()
        self.event = Event.objects.create(
            title='E2', slug='e2', description='d',
            short_description='0700000000', category=self.cat,
            organizer=self.org,
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=31),
            status=Event.Status.PUBLISHED,
            commission_rate=Decimal('8.00'),
        )
        self.tt = TicketType.objects.create(
            event=self.event, name='Std',
            price=Decimal('5000'), quantity=100,
        )
        self.order = GuestOrder.objects.create(
            first_name='B', last_name='E',
            email='b@test.com', phone='+2250700000000',
            total=Decimal('5000'),
            status=GuestOrder.Status.PAID,
        )
        item = GuestOrderItem.objects.create(
            order=self.order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('5000'),
        )
        # Créer un GuestTicket — nécessaire pour que guest_tickets_confirmed
        # aille jusqu'à l'envoi du SMS
        from apps.tickets.models import GuestTicket
        GuestTicket.objects.create(
            order_item=item,
            ticket_number='TK-TEST-SMS-001',
            status=GuestTicket.Status.VALID,
        )

    @patch('apps.notifications.sms.send_sms')
    def test_guest_ticket_sms_contains_link(self, mock_send_sms):
        """Le SMS de confirmation billet doit contenir /b/<access_token>/."""
        from apps.notifications.service import NotificationService
        NotificationService.guest_tickets_confirmed(self.order)

        self.assertTrue(mock_send_sms.called)
        args, kwargs = mock_send_sms.call_args
        sms_body = args[1]
        self.assertIn('/b/', sms_body)
        self.assertIn(str(self.order.access_token), sms_body)
        # Le SMS doit faire moins de 160 caractères (1 segment)
        self.assertLess(len(sms_body), 160, f"SMS trop long ({len(sms_body)} chars) : {sms_body}")
