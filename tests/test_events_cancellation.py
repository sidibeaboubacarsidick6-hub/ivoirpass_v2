"""
Tests de l'annulation d'événement — apps/events/services.py

Couvre :
- Annulation avec tickets vendus → wallet gelé
- Annulation sans ventes → wallet non gelé
- Tickets passent VOID
- Orders passent CANCELLED
- Emails + SMS envoyés aux acheteurs
- Alerte admin envoyée
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.dashboard.models import OrganizerWallet, AuditLog
from apps.events.models import Category, Event, TicketType
from apps.events.services import cancel_event_organizer_liable
from apps.tickets.models import (
    Order, OrderItem, Ticket,
    GuestOrder, GuestOrderItem, GuestTicket,
)


def _make_organizer(email='org-cancel@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass',
        first_name='Org', last_name='Test',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_event(organizer, suffix='x'):
    cat, _ = Category.objects.get_or_create(
        slug=f'cat-cancel-{suffix}',
        defaults={'name': f'Cat {suffix}'},
    )
    now = timezone.now()
    event = Event.objects.create(
        title=f'Event {suffix}',
        slug=f'event-cancel-{suffix}',
        description='d',
        short_description='0700000000',
        category=cat,
        organizer=organizer,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=31),
        status=Event.Status.PUBLISHED,
        commission_rate=Decimal('8.00'),
    )
    tt = TicketType.objects.create(
        event=event, name='Standard',
        price=Decimal('10000'), quantity=100,
    )
    return event, tt


class CancelEventWithSalesTests(TestCase):
    """Annulation d'un événement qui a des ventes."""

    def setUp(self):
        self.org = _make_organizer()
        self.event, self.tt = _make_event(self.org, 'with-sales')

    def _make_paid_guest_order(self, email='buyer@test.com'):
        order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email=email, phone='+2250700000000',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        order.mark_as_paid(payment_method='paydunya', payment_reference='tx_1')
        return order

    @patch('apps.notifications.service.NotificationService.event_cancelled_buyer')
    @patch('apps.notifications.service.NotificationService.event_cancelled_admin_alert')
    def test_annulation_avec_vente_gele_wallet(self, mock_admin, mock_buyer):
        """Avec ventes → wallet gelé + tickets void + orders cancelled."""
        order = self._make_paid_guest_order()

        result = cancel_event_organizer_liable(
            self.event, reason='Test annulation',
        )

        self.assertEqual(result['orders_affected'], 1)
        self.assertEqual(result['tickets_voided'], 1)
        self.assertTrue(result['wallet_frozen'])

        # Vérifie wallet gelé
        wallet = OrganizerWallet.objects.get(organizer=self.org)
        self.assertTrue(wallet.is_frozen)
        self.assertIn(self.event.title, wallet.frozen_reason)
        self.assertIn('Test annulation', wallet.frozen_reason)

        # Vérifie tickets VOID
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.CANCELLED)
        ticket = GuestTicket.objects.get(order_item__order=order)
        self.assertEqual(ticket.status, GuestTicket.Status.VOID)

        # Vérifie l'event
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CANCELLED)

    @patch('apps.notifications.service.NotificationService.event_cancelled_buyer')
    @patch('apps.notifications.service.NotificationService.event_cancelled_admin_alert')
    def test_annulation_envoie_emails(self, mock_admin, mock_buyer):
        """Les emails acheteur + admin sont envoyés."""
        self._make_paid_guest_order('buyer-mails@test.com')

        cancel_event_organizer_liable(self.event)

        mock_buyer.assert_called_once()
        call_kwargs = mock_buyer.call_args.kwargs
        self.assertEqual(call_kwargs['buyer_email'], 'buyer-mails@test.com')

        mock_admin.assert_called_once()

    @patch('apps.notifications.service.NotificationService.event_cancelled_buyer')
    @patch('apps.notifications.service.NotificationService.event_cancelled_admin_alert')
    def test_annulation_plusieurs_orders(self, mock_admin, mock_buyer):
        """3 commandes payées → 3 emails, 3 tickets void."""
        for i in range(3):
            self._make_paid_guest_order(f'buyer{i}@test.com')

        result = cancel_event_organizer_liable(self.event)

        self.assertEqual(result['orders_affected'], 3)
        self.assertEqual(result['tickets_voided'], 3)
        self.assertEqual(mock_buyer.call_count, 3)


class CancelEventWithoutSalesTests(TestCase):
    """Annulation d'un événement sans ventes."""

    def setUp(self):
        self.org = _make_organizer('org-nosales@test.com')
        self.event, self.tt = _make_event(self.org, 'no-sales')

    @patch('apps.notifications.service.NotificationService.event_cancelled_buyer')
    @patch('apps.notifications.service.NotificationService.event_cancelled_admin_alert')
    def test_annulation_sans_vente_ne_gele_pas_wallet(self, mock_admin, mock_buyer):
        """Sans ventes → wallet PAS gelé."""
        result = cancel_event_organizer_liable(self.event)

        self.assertEqual(result['orders_affected'], 0)
        self.assertEqual(result['tickets_voided'], 0)
        self.assertFalse(result['wallet_frozen'])

        wallet, _ = OrganizerWallet.objects.get_or_create(organizer=self.org)
        self.assertFalse(wallet.is_frozen)

        # Aucun email acheteur (pas de ventes)
        mock_buyer.assert_not_called()
        # Admin alerté quand même
        mock_admin.assert_called_once()


class CancelEventWithAccountOrdersTests(TestCase):
    """Annulation avec commandes 'avec compte' (legacy)."""

    def setUp(self):
        self.org = _make_organizer('org-account@test.com')
        self.event, self.tt = _make_event(self.org, 'with-account')

    @patch('apps.notifications.service.NotificationService.event_cancelled_buyer')
    @patch('apps.notifications.service.NotificationService.event_cancelled_admin_alert')
    def test_annulation_account_order(self, mock_admin, mock_buyer):
        """Order PAID legacy → tickets void + email envoyé."""
        buyer = CustomUser.objects.create_user(
            email='accbuyer@test.com', password='pass',
            first_name='Acc', last_name='Buyer',
        )
        buyer.phone_number = '+2250700000001'
        buyer.save()

        order = Order.objects.create(
            buyer=buyer, subtotal=Decimal('10000'),
            commission=0, total=Decimal('10000'),
        )
        OrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        order.mark_as_paid(payment_method='paydunya', payment_reference='tx_acc')

        result = cancel_event_organizer_liable(self.event)

        self.assertEqual(result['orders_affected'], 1)
        self.assertEqual(result['tickets_voided'], 1)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

        # L'email est envoyé avec le bon destinataire + téléphone
        mock_buyer.assert_called_once()
        kwargs = mock_buyer.call_args.kwargs
        self.assertEqual(kwargs['buyer_email'], 'accbuyer@test.com')
        self.assertEqual(kwargs['buyer_phone'], '+2250700000001')