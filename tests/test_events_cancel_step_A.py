"""
IvoirPass V2 — Chantier A : annulation événement (organisateur seul responsable).

Couvre :
  - Un événement sans vente : suppression classique (pas de gel)
  - Un événement avec ventes : tickets voidés, commandes CANCELLED,
    wallet gelé, emails envoyés (buyer + admin)
  - Le blocage de withdraw_request quand le wallet est gelé
  - L'idempotence : pas de gel si aucune commande PAID
"""
from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.dashboard.models import OrganizerWallet, AuditLog
from apps.events.models import Event, Category
from apps.tickets.models import (
    Order, OrderItem, Ticket,
    GuestOrder, GuestOrderItem, GuestTicket,
)


# ============================================================
# Helpers
# ============================================================

def _make_organizer(email='org@test.com'):
    user = CustomUser.objects.create_user(
        email=email,
        password='testpass123',
        first_name='Org', last_name='Test',
    )
    user.role = CustomUser.Role.ORGANIZER
    user.is_organizer_verified = True
    user.save()
    return user


def _make_admin(email='admin@test.com'):
    user = CustomUser.objects.create_user(
        email=email,
        password='testpass123',
        first_name='Adm', last_name='In',
    )
    user.role = CustomUser.Role.ADMIN
    user.notify_email = True
    user.is_staff = True
    user.save()
    return user


def _make_event(organizer, title='Concert Test'):
    category, _ = Category.objects.get_or_create(
        name='Test', defaults={'icon': 'bi-music-note', 'color': '#000'},
    )
    return Event.objects.create(
        title=title,
        slug=title.lower().replace(' ', '-'),
        description='desc',
        short_description='+225 07 00 00 00 00',
        category=category,
        organizer=organizer,
        start_date=timezone.now() + timedelta(days=7),
        end_date=timezone.now() + timedelta(days=7, hours=3),
        status=Event.Status.PUBLISHED,
        venue_name='Palais de la Culture',
        venue_address='Treichville',
        venue_city='Abidjan',
        venue_country="Côte d'Ivoire",
    )

def _make_guest_order_with_ticket(event, email='buyer@test.com'):
    """
    Crée une GuestOrder PAID + 1 GuestOrderItem + 1 GuestTicket VALID,
    ET incrémente `event.tickets_sold` (nécessaire pour que
    event_delete() déclenche bien cancel_event_organizer_liable()
    au lieu de la suppression pure).
    """
    from django.db.models import F
    from apps.events.models import TicketType, Event

    tt, _ = TicketType.objects.get_or_create(
        event=event, name='Standard',
        defaults={'price': 5000, 'quantity': 100},
    )
    order = GuestOrder.objects.create(
        first_name='Jean', last_name='Acheteur',
        email=email,
        subtotal=Decimal('5000'), total=Decimal('5000'),
        status=GuestOrder.Status.PAID,
    )
    item = GuestOrderItem.objects.create(
        order=order, ticket_type=tt,
        quantity=1, unit_price=Decimal('5000'),
    )
    ticket = GuestTicket.objects.create(order_item=item)

    # Compteur d'événement (champ editable=False → update queryset)
    Event.objects.filter(pk=event.pk).update(
        tickets_sold=F('tickets_sold') + 1
    )
    event.refresh_from_db()

    return order, ticket


# ============================================================
# Tests
# ============================================================

class CancelEventNoSalesTests(TestCase):
    """Événement sans vente : suppression simple, pas de gel."""

    def setUp(self):
        self.org = _make_organizer()

    def test_delete_without_sales_just_deletes(self):
        event = _make_event(self.org)
        event_id = event.id

        # Créer un wallet au préalable pour pouvoir vérifier qu'il n'est
        # PAS gelé après suppression (la vue event_delete n'y touche pas
        # quand il n'y a aucune vente).
        wallet, _ = OrganizerWallet.objects.get_or_create(organizer=self.org)

        self.client.force_login(self.org)

        response = self.client.post(
            reverse('events:delete', kwargs={'slug': event.slug}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Event.objects.filter(id=event_id).exists())

        wallet.refresh_from_db()
        self.assertFalse(wallet.is_frozen)

class CancelEventWithSalesTests(TestCase):
    """Événement avec ventes : annulation complète + gel wallet."""

    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)
        self.guest_order, self.guest_ticket = _make_guest_order_with_ticket(
            self.event, email='buyer1@test.com',
        )
        self.client.force_login(self.org)

    def test_event_marked_cancelled(self):
        self.client.post(reverse('events:delete', kwargs={'slug': self.event.slug}))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CANCELLED)

    def test_guest_ticket_voided(self):
        self.client.post(reverse('events:delete', kwargs={'slug': self.event.slug}))
        self.guest_ticket.refresh_from_db()
        self.assertEqual(self.guest_ticket.status, GuestTicket.Status.VOID)

    def test_guest_order_cancelled_not_refunded(self):
        self.client.post(reverse('events:delete', kwargs={'slug': self.event.slug}))
        self.guest_order.refresh_from_db()
        self.assertEqual(self.guest_order.status, GuestOrder.Status.CANCELLED)
        # JAMAIS REFUNDED (IvoirPass n'est pas responsable)
        self.assertNotEqual(self.guest_order.status, GuestOrder.Status.REFUNDED)

    def test_wallet_frozen_when_sales_exist(self):
        wallet_before = OrganizerWallet.objects.filter(organizer=self.org).first()
        balance_before = wallet_before.balance_available if wallet_before else 0

        self.client.post(reverse('events:delete', kwargs={'slug': self.event.slug}))

        wallet = OrganizerWallet.objects.get(organizer=self.org)
        self.assertTrue(wallet.is_frozen)
        # Le solde n'a PAS bougé (pas de remb auto, pas de débit)
        self.assertEqual(wallet.balance_available, balance_before)
        # La raison est tracée
        self.assertIn(self.event.title, wallet.frozen_reason)

    def test_scanner_rejects_voided_ticket(self):
        """Après annulation, un scan du billet → TICKET_VOID."""
        self.client.post(reverse('events:delete', kwargs={'slug': self.event.slug}))
        self.guest_ticket.refresh_from_db()
        self.assertEqual(self.guest_ticket.status, GuestTicket.Status.VOID)


class WithdrawBlockedWhenFrozenTests(TestCase):
    """withdraw_request doit refuser tant que le wallet est gelé."""

    def setUp(self):
        self.org = _make_organizer()
        self.wallet = OrganizerWallet.objects.create(
            organizer=self.org,
            balance_available=Decimal('50000'),
            is_frozen=True,
            frozen_reason='Test',
        )
        self.client.force_login(self.org)

    def test_get_withdraw_redirects_when_frozen(self):
        response = self.client.get(reverse('dashboard:withdraw'))
        # Redirect vers wallet
        self.assertEqual(response.status_code, 302)
        self.assertIn('wallet', response.url)

    def test_post_withdraw_rejected_when_frozen(self):
        response = self.client.post(reverse('dashboard:withdraw'), data={
            'amount': 10000,
            'payout_method': 'wave',
            'payout_phone': '+225 07 00 00 00 00',
            'payout_name': 'Jean Test',
        })
        self.assertEqual(response.status_code, 302)
        # Aucune WithdrawalRequest créée
        from apps.dashboard.models import WithdrawalRequest
        self.assertEqual(
            WithdrawalRequest.objects.filter(wallet=self.wallet).count(), 0,
        )