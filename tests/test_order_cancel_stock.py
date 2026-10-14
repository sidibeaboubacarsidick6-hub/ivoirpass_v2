"""
Test — restitution automatique du stock quand une commande passe
de PENDING à CANCELLED (bug identifié le 2026-10-14 sur preprod).
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.events.models import Category, Event, TicketType
from apps.tickets.models import GuestOrder, GuestOrderItem


User = get_user_model()


class GuestOrderCancelReleasesStockTests(TestCase):
    """Vérifie que le signal libère bien le stock à l'annulation."""

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='organizer@test.com',
            password='test1234',
            first_name='Org', last_name='A',
            role=User.Role.ORGANIZER,
        )
        self.category = Category.objects.create(name='Test Cat', slug='test-cat')
        now = timezone.now()
        self.event = Event.objects.create(
            title='Event Test',
            slug='event-test',
            description='d',
            short_description='0700000000',
            category=self.category,
            organizer=self.organizer,
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=31),
            status=Event.Status.PUBLISHED,
            commission_rate=Decimal('8.00'),
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event, name='Standard',
            price=Decimal('5000'), quantity=100,
        )

    def _create_pending_guest_order(self, quantity=2):
        """Crée une commande guest PENDING avec le stock réservé."""
        order = GuestOrder.objects.create(
            first_name='Buy', last_name='Er',
            email='buyer@test.com',
            phone='+22507000000',
            total=Decimal('5000') * quantity,
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.ticket_type,
            quantity=quantity, unit_price=Decimal('5000'),
        )
        # Simuler la réservation initiale (normalement faite dans la vue)
        self.ticket_type.quantity_sold += quantity
        self.event.tickets_sold += quantity
        self.ticket_type.save(update_fields=['quantity_sold'])
        self.event.save(update_fields=['tickets_sold'])
        return order

    def test_cancel_releases_stock(self):
        """Annulation manuelle → stock restitué."""
        order = self._create_pending_guest_order(quantity=2)

        self.ticket_type.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.event.tickets_sold, 2)
        self.assertEqual(self.ticket_type.quantity_sold, 2)

        # Annuler la commande (comme le ferait la vue guest_payment_cancel)
        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        self.ticket_type.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(self.event.tickets_sold, 0, "Le compteur event n'a pas été décrémenté")
        self.assertEqual(self.ticket_type.quantity_sold, 0, "Le compteur ticket_type n'a pas été décrémenté")

    def test_no_release_if_already_cancelled(self):
        """Annuler 2× ne doit pas décrémenter 2× (idempotence)."""
        order = self._create_pending_guest_order(quantity=2)

        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        # 2e save avec le même statut
        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        self.event.refresh_from_db()
        self.assertEqual(self.event.tickets_sold, 0)

    def test_no_release_if_paid(self):
        """Commande PAID → CANCELLED (annulation d'événement) : pas de décrémentation."""
        order = self._create_pending_guest_order(quantity=2)

        # Simuler un paiement confirmé
        order.status = GuestOrder.Status.PAID
        order.save(update_fields=['status'])

        # Puis annulation d'événement
        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        self.event.refresh_from_db()
        # Le stock NE DOIT PAS avoir bougé (les billets ont été émis)
        self.assertEqual(self.event.tickets_sold, 2)
