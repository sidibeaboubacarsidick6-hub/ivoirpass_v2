"""
Tests de la tâche release_expired_pending_orders (2 vitesses) :
- PENDING sans token, > 30 min → annulée
- PENDING avec token, > 30 min mais < 24h → conservée
- PENDING avec token, > 24h → annulée
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.events.models import Category, Event, TicketType
from apps.payments.models import Payment
from apps.payments.tasks import release_expired_pending_orders
from apps.tickets.models import GuestOrder, GuestOrderItem


User = get_user_model()


class ReleaseExpiredOrdersTests(TestCase):

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='org@test.com', password='test1234',
            first_name='Org', last_name='A',
            role=User.Role.ORGANIZER,
        )
        self.cat = Category.objects.create(name='Cat', slug='cat')
        now = timezone.now()
        self.event = Event.objects.create(
            title='Event', slug='event', description='d',
            short_description='0700000000', category=self.cat,
            organizer=self.organizer,
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=31),
            status=Event.Status.PUBLISHED,
            commission_rate=Decimal('8.00'),
        )
        self.tt = TicketType.objects.create(
            event=self.event, name='Std',
            price=Decimal('5000'), quantity=100,
        )

    def _create_pending_order(self, minutes_old, has_token=False):
        """Crée une commande PENDING avec un age spécifié."""
        order = GuestOrder.objects.create(
            first_name='Buy', last_name='Er',
            email=f'buyer-{minutes_old}-{has_token}@test.com',
            phone='+22507000000',
            total=Decimal('5000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('5000'),
        )
        # Simuler la réservation
        self.tt.quantity_sold += 1
        self.event.tickets_sold += 1
        self.tt.save(update_fields=['quantity_sold'])
        self.event.save(update_fields=['tickets_sold'])

        # Créer un Payment
        Payment.objects.create(
            guest_order=order,
            amount=Decimal('5000'),
            status=Payment.Status.PENDING,
            paydunya_token='tok_abc123' if has_token else '',
        )

        # Ajuster created_at (auto_now_add ignore les kwarg, donc update manuel)
        old_date = timezone.now() - timedelta(minutes=minutes_old)
        GuestOrder.objects.filter(pk=order.pk).update(created_at=old_date)
        order.refresh_from_db()
        return order

    def test_no_token_old_order_is_cancelled(self):
        """Sans token, > 30 min → annulée."""
        order = self._create_pending_order(minutes_old=45, has_token=False)
        release_expired_pending_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.CANCELLED)
        self.event.refresh_from_db()
        self.assertEqual(self.event.tickets_sold, 0)

    def test_token_but_recent_order_is_kept(self):
        """Avec token, 2h → conservée (toujours dans la fenêtre 24h)."""
        order = self._create_pending_order(minutes_old=120, has_token=True)
        release_expired_pending_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.PENDING)
        self.event.refresh_from_db()
        self.assertEqual(self.event.tickets_sold, 1)

    def test_token_and_old_order_is_cancelled(self):
        """Avec token, > 24h → annulée."""
        order = self._create_pending_order(minutes_old=25 * 60, has_token=True)
        release_expired_pending_orders()
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.CANCELLED)
        self.event.refresh_from_db()
        self.assertEqual(self.event.tickets_sold, 0)
