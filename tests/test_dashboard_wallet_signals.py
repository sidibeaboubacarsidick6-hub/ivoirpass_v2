"""
Tests du crédit wallet automatique — apps/dashboard/signals.py

Couvre :
- Crédit wallet depuis Order PAID
- Crédit wallet depuis GuestOrder PAID
- Anti-double-crédit (2 appels → 1 seul crédit)
- Calcul de la commission (8 % par défaut)
- Commandes multi-organisateurs (plusieurs wallets crédités)
- Commandes sans PAID → pas de crédit
"""
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import CustomUser
from apps.dashboard.models import OrganizerWallet, WalletTransaction
from apps.events.models import Category, Event, TicketType
from apps.tickets.models import (
    Order, OrderItem, GuestOrder, GuestOrderItem,
)


def _make_organizer(email, commission_rate='8.00'):
    """Crée un organisateur avec un événement à 1 type de billet."""
    u = CustomUser.objects.create_user(
        email=email, password='pass',
        first_name='Org', last_name='Test',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()

    cat, _ = Category.objects.get_or_create(
        slug=f'cat-{email.split("@")[0]}',
        defaults={'name': f'Cat {email}'},
    )

    from django.utils import timezone
    now = timezone.now()
    event = Event.objects.create(
        title=f'Event {email}',
        slug=f'event-{email.split("@")[0]}',
        description='d',
        short_description='0700000000',
        category=cat,
        organizer=u,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=31),
        status=Event.Status.PUBLISHED,
        commission_rate=Decimal(commission_rate),
    )
    tt = TicketType.objects.create(
        event=event, name='Standard',
        price=Decimal('10000'), quantity=100,
    )
    return u, event, tt


class WalletCreditFromOrderTests(TestCase):
    """Tests du signal post_save sur Order."""

    def setUp(self):
        self.org, self.event, self.tt = _make_organizer('org1@test.com')

    def test_order_paid_credite_wallet_avec_commission(self):
        """Order PAID → wallet crédité du NET (10000 - 8% = 9200)."""
        buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='pass',
        )
        order = Order.objects.create(
            buyer=buyer, subtotal=Decimal('10000'),
            commission=0, total=Decimal('10000'),
            status=Order.Status.PENDING,
        )
        OrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

        # Passe en PAID → déclenche le signal
        order.mark_as_paid(payment_method='paydunya', payment_reference='tx_1')

        wallet = OrganizerWallet.objects.get(organizer=self.org)
        self.assertEqual(wallet.balance_events_available, 9200)

        tx = WalletTransaction.objects.get(
            wallet=wallet, reference=order.order_number,
        )
        self.assertEqual(tx.amount, 9200)
        self.assertEqual(tx.source, 'events')
        self.assertEqual(tx.type, WalletTransaction.Type.CREDIT)

    def test_order_pending_ne_credite_pas(self):
        """Order PENDING → pas de crédit."""
        buyer = CustomUser.objects.create_user(
            email='buyer2@test.com', password='pass',
        )
        Order.objects.create(
            buyer=buyer, subtotal=Decimal('10000'),
            commission=0, total=Decimal('10000'),
            status=Order.Status.PENDING,
        )

        wallet, _ = OrganizerWallet.objects.get_or_create(organizer=self.org)
        self.assertEqual(wallet.balance_events_available, 0)

    def test_double_mark_as_paid_ne_credite_pas_deux_fois(self):
        """2 appels à mark_as_paid → 1 seul crédit wallet."""
        buyer = CustomUser.objects.create_user(
            email='buyer3@test.com', password='pass',
        )
        order = Order.objects.create(
            buyer=buyer, subtotal=Decimal('10000'),
            commission=0, total=Decimal('10000'),
        )
        OrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

        first = order.mark_as_paid(payment_method='paydunya', payment_reference='tx_a')
        second = order.mark_as_paid(payment_method='paydunya', payment_reference='tx_a')

        self.assertTrue(first)
        self.assertFalse(second)

        wallet = OrganizerWallet.objects.get(organizer=self.org)
        self.assertEqual(wallet.balance_events_available, 9200)  # PAS 18400

    def test_commande_multi_organisateurs_credite_chaque_wallet(self):
        """1 commande avec 2 billets de 2 organisateurs → 2 wallets crédités."""
        org2, event2, tt2 = _make_organizer('org2@test.com')

        buyer = CustomUser.objects.create_user(
            email='buyer4@test.com', password='pass',
        )
        order = Order.objects.create(
            buyer=buyer, subtotal=Decimal('20000'),
            commission=0, total=Decimal('20000'),
        )
        OrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )
        OrderItem.objects.create(
            order=order, ticket_type=tt2,
            quantity=1, unit_price=Decimal('10000'),
        )

        order.mark_as_paid(payment_method='paydunya', payment_reference='tx_multi')

        w1 = OrganizerWallet.objects.get(organizer=self.org)
        w2 = OrganizerWallet.objects.get(organizer=org2)
        self.assertEqual(w1.balance_events_available, 9200)
        self.assertEqual(w2.balance_events_available, 9200)


class WalletCreditFromGuestOrderTests(TestCase):
    """Tests du signal post_save sur GuestOrder."""

    def setUp(self):
        self.org, self.event, self.tt = _make_organizer('org-guest@test.com')

    def test_guest_order_paid_credite_wallet(self):
        """GuestOrder PAID → wallet crédité du NET."""
        order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali@test.com', phone='0700000000',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

        order.mark_as_paid(payment_method='paydunya', payment_reference='tx_g1')

        wallet = OrganizerWallet.objects.get(organizer=self.org)
        self.assertEqual(wallet.balance_events_available, 9200)

    def test_guest_order_commission_figee(self):
        """Le champ commission est figé sur GuestOrder PAID."""
        order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali2@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.PENDING,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=2, unit_price=Decimal('10000'),
        )

        order.mark_as_paid(payment_method='paydunya', payment_reference='tx_g2')

        order.refresh_from_db()
        # 20000 * 8% = 1600 FCFA de commission
        self.assertEqual(order.commission, 1600)

    def test_guest_order_annulee_ne_credite_pas(self):
        """GuestOrder CANCELLED → mark_as_paid retourne False, pas de crédit."""
        order = GuestOrder.objects.create(
            first_name='Ali', last_name='B',
            email='ali3@test.com',
            subtotal=Decimal('10000'), total=Decimal('10000'),
            status=GuestOrder.Status.CANCELLED,
        )
        GuestOrderItem.objects.create(
            order=order, ticket_type=self.tt,
            quantity=1, unit_price=Decimal('10000'),
        )

        result = order.mark_as_paid(payment_method='paydunya', payment_reference='tx_g3')

        self.assertFalse(result)
        wallet, _ = OrganizerWallet.objects.get_or_create(organizer=self.org)
        self.assertEqual(wallet.balance_events_available, 0)


class WalletCreditIdempotenceTests(TestCase):
    """Tests d'idempotence de la contrainte unique."""

    def setUp(self):
        self.org, self.event, self.tt = _make_organizer('org-idem@test.com')

    def test_un_seul_credit_par_reference(self):
        """Deux WalletTransactions avec la même référence+type=credit sont refusées."""
        from django.db import IntegrityError, transaction

        wallet, _ = OrganizerWallet.objects.get_or_create(organizer=self.org)

        WalletTransaction.objects.create(
            wallet=wallet, type=WalletTransaction.Type.CREDIT,
            amount=1000, balance_after=1000,
            source='events', reference='REF-UNIQUE',
            description='Test',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WalletTransaction.objects.create(
                    wallet=wallet, type=WalletTransaction.Type.CREDIT,
                    amount=1000, balance_after=2000,
                    source='events', reference='REF-UNIQUE',
                    description='Doublon',
                )