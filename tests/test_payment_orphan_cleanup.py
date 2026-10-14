"""
Test — annulation automatique des Payment PENDING quand la commande
associée passe en CANCELLED (bug 2026-10-14).
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.events.models import Category, Event, TicketType
from apps.payments.models import Payment
from apps.tickets.models import GuestOrder, GuestOrderItem


User = get_user_model()


class PaymentCanceledWithOrderTests(TestCase):

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

    def _create_order_with_payment(self):
        order = GuestOrder.objects.create(
            first_name='B', last_name='E',
            email='b@test.com', phone='+2250700000000',
            total=Decimal('5000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('5000'),
        )
        self.tt.quantity_sold += 1
        self.event.tickets_sold += 1
        self.tt.save(update_fields=['quantity_sold'])
        self.event.save(update_fields=['tickets_sold'])

        payment = Payment.objects.create(
            guest_order=order,
            amount=Decimal('5000'),
            status=Payment.Status.PENDING,
            paydunya_token='tok_test',
        )
        return order, payment

    def test_payment_cancelled_with_order(self):
        """Annulation commande → Payment PENDING devient CANCELLED."""
        order, payment = self._create_order_with_payment()
        self.assertEqual(payment.status, Payment.Status.PENDING)

        # Annuler la commande (déclenche le signal)
        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        payment.refresh_from_db()
        self.assertEqual(
            payment.status, Payment.Status.CANCELLED,
            "Le Payment aurait dû passer en CANCELLED automatiquement",
        )

    def test_completed_payment_not_touched(self):
        """Un Payment déjà COMPLETED n'est pas modifié."""
        order, payment = self._create_order_with_payment()
        payment.status = Payment.Status.COMPLETED
        payment.save(update_fields=['status'])

        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
