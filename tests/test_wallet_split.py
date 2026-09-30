"""
Tests Vague 3.1 — Wallet divisé (events / store) — 2026-09-30.

Vérifie :
- Les propriétés calculées (balance_available, balance_pending)
- credit() avec source events / store
- reserve() / release_reserved() / complete_reserved() par source
- refund_charge() par source
- Isolation : un solde store ne peut pas financer un reversement events
"""
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import CustomUser
from apps.dashboard.models import (
    OrganizerWallet, WalletTransaction, WithdrawalRequest,
)


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='O', last_name='G',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


class WalletSplitCreditTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.wallet = OrganizerWallet.objects.create(organizer=self.org)

    # ── Credit ────────────────────────────────────────────────

    def test_credit_events(self):
        self.wallet.credit(10000, source='events', reference='T-EV-1')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 10000)
        self.assertEqual(self.wallet.balance_store_available, 0)
        self.assertEqual(self.wallet.balance_available, 10000)

    def test_credit_store(self):
        self.wallet.credit(5000, source='store', reference='T-ST-1')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 0)
        self.assertEqual(self.wallet.balance_store_available, 5000)
        self.assertEqual(self.wallet.balance_available, 5000)

    def test_credit_source_inconnue_leve_erreur(self):
        with self.assertRaises(ValueError):
            self.wallet.credit(1000, source='foo', reference='T-X')

    def test_credit_accumule_par_source(self):
        self.wallet.credit(10000, source='events', reference='T-EV-1')
        self.wallet.credit(5000,  source='events', reference='T-EV-2')
        self.wallet.credit(3000,  source='store',  reference='T-ST-1')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 15000)
        self.assertEqual(self.wallet.balance_store_available, 3000)
        self.assertEqual(self.wallet.balance_available, 18000)

    def test_credit_trace_source_dans_wallettransaction(self):
        self.wallet.credit(1000, source='store', reference='T-X')
        tx = WalletTransaction.objects.get(reference='T-X')
        self.assertEqual(tx.source, 'store')
        self.assertEqual(tx.type, WalletTransaction.Type.CREDIT)


class WalletSplitReserveTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.wallet = OrganizerWallet.objects.create(organizer=self.org)
        self.wallet.credit(10000, source='events', reference='C-EV')
        self.wallet.credit(5000,  source='store',  reference='C-ST')
        self.wallet.refresh_from_db()

    # ── Reserve ───────────────────────────────────────────────

    def test_reserve_events(self):
        self.wallet.reserve(3000, source='events', reference='R-1')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 7000)
        self.assertEqual(self.wallet.balance_events_pending, 3000)
        self.assertEqual(self.wallet.balance_store_available, 5000)

    def test_reserve_store(self):
        self.wallet.reserve(2000, source='store', reference='R-2')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_store_available, 3000)
        self.assertEqual(self.wallet.balance_store_pending, 2000)
        self.assertEqual(self.wallet.balance_events_available, 10000)

    def test_reserve_events_avec_solde_store_insuffisant_refuse(self):
        """Un reversement events ne peut PAS piocher dans le store."""
        with self.assertRaises(ValueError):
            self.wallet.reserve(15000, source='events', reference='R-X')

    def test_reserve_store_avec_solde_events_insuffisant_refuse(self):
        """Un reversement store ne peut PAS piocher dans les events."""
        with self.assertRaises(ValueError):
            self.wallet.reserve(8000, source='store', reference='R-Y')


class WalletSplitReleaseCompleteTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.wallet = OrganizerWallet.objects.create(organizer=self.org)
        self.wallet.credit(10000, source='events', reference='C-EV')
        self.wallet.credit(5000,  source='store',  reference='C-ST')
        self.wallet.refresh_from_db()

    # ── Release ───────────────────────────────────────────────

    def test_release_events_remet_dispo(self):
        self.wallet.reserve(3000, source='events', reference='R-1')
        self.wallet.release_reserved(3000, source='events', reference='R-1')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 10000)
        self.assertEqual(self.wallet.balance_events_pending, 0)

    def test_release_store_remet_dispo(self):
        self.wallet.reserve(2000, source='store', reference='R-2')
        self.wallet.release_reserved(2000, source='store', reference='R-2')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_store_available, 5000)
        self.assertEqual(self.wallet.balance_store_pending, 0)

    # ── Complete ──────────────────────────────────────────────

    def test_complete_events_ajoute_aux_retraits(self):
        self.wallet.reserve(3000, source='events', reference='R-3')
        self.wallet.complete_reserved(3000, source='events', reference='R-3')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 7000)
        self.assertEqual(self.wallet.balance_events_pending, 0)
        self.assertEqual(self.wallet.balance_withdrawn, 3000)

    def test_complete_store_ajoute_aux_retraits(self):
        self.wallet.reserve(2000, source='store', reference='R-4')
        self.wallet.complete_reserved(2000, source='store', reference='R-4')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_store_available, 3000)
        self.assertEqual(self.wallet.balance_store_pending, 0)
        self.assertEqual(self.wallet.balance_withdrawn, 2000)


class WalletSplitRefundTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.wallet = OrganizerWallet.objects.create(organizer=self.org)
        self.wallet.credit(10000, source='events', reference='C-EV')
        self.wallet.credit(5000,  source='store',  reference='C-ST')
        self.wallet.refresh_from_db()

    def test_refund_events(self):
        self.wallet.refund_charge(2000, source='events', reference='RF-1')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 8000)
        self.assertEqual(self.wallet.balance_store_available, 5000)

    def test_refund_store(self):
        self.wallet.refund_charge(1000, source='store', reference='RF-2')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_available, 10000)
        self.assertEqual(self.wallet.balance_store_available, 4000)


class WalletSplitWithdrawalSourceTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.wallet = OrganizerWallet.objects.create(organizer=self.org)
        self.wallet.credit(10000, source='events', reference='C-EV')
        self.wallet.refresh_from_db()

    def test_withdrawal_avec_source_events(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=3000, fee=0, amount_net=3000,
            payout_method='wave', payout_phone='0700000000',
            payout_name='Test', source='events',
        )
        self.assertEqual(wr.source, 'events')
        self.assertEqual(wr.get_source_display(), 'Événements')

    def test_withdrawal_default_source_events(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=3000, fee=0, amount_net=3000,
            payout_method='wave', payout_phone='0700000000',
            payout_name='Test',
        )
        self.assertEqual(wr.source, 'events')