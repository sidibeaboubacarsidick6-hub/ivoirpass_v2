"""
Tests de l'admin dashboard — apps/dashboard/admin.py
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.admin.sites import AdminSite

from apps.accounts.models import CustomUser
from apps.dashboard.models import (
    OrganizerWallet, WalletTransaction, WithdrawalRequest,
    AuditLog, Dispute,
)
from apps.dashboard.admin import (
    OrganizerWalletAdmin, WithdrawalRequestAdmin,
    DisputeAdmin, AuditLogAdmin, WalletTransactionAdmin,
)


def _make_admin(email='admin@test.com'):
    u = CustomUser.objects.create_user(email=email, password='pass')
    u.is_staff = True
    u.is_superuser = True
    u.save()
    return u


def _make_organizer_wallet(email='org@test.com'):
    u = CustomUser.objects.create_user(email=email, password='pass')
    u.role = CustomUser.Role.ORGANIZER
    u.save()
    wallet, _ = OrganizerWallet.objects.get_or_create(organizer=u)
    return u, wallet


class OrganizerWalletAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = OrganizerWalletAdmin(OrganizerWallet, self.site)

    def test_has_add_permission_false(self):
        """Impossible de créer un wallet manuellement."""
        request = type('R', (), {'user': _make_admin()})()
        self.assertFalse(self.admin.has_add_permission(request))

    def test_unfreeze_aucun_gel(self):
        """Action sur aucun wallet gelé → message warning, pas de redirect."""
        admin_user = _make_admin('adm-unf@test.com')
        request = type('R', (), {
            'user': admin_user,
            'META': {'REMOTE_ADDR': '127.0.0.1'},
        })()
        # Singleton 'message_user' va planter → on mock
        self.admin.message_user = lambda *a, **kw: None

        _, wallet = _make_organizer_wallet('o-unf@test.com')
        # wallet non gelé par défaut
        queryset = OrganizerWallet.objects.filter(pk=wallet.pk)
        result = self.admin.unfreeze_wallets(request, queryset)
        self.assertIsNone(result)


class WithdrawalRequestAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = WithdrawalRequestAdmin(WithdrawalRequest, self.site)

    def test_source_badge_events(self):
        _, wallet = _make_organizer_wallet('w-src@test.com')
        wr = WithdrawalRequest.objects.create(
            wallet=wallet, amount=Decimal('1000'), fee=0, amount_net=Decimal('1000'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='X',
            source='events',
        )
        html = self.admin.source_badge(wr)
        self.assertIn('Événements', html)

    def test_source_badge_store(self):
        _, wallet = _make_organizer_wallet('w-src2@test.com')
        wr = WithdrawalRequest.objects.create(
            wallet=wallet, amount=Decimal('1000'), fee=0, amount_net=Decimal('1000'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='X',
            source='store',
        )
        html = self.admin.source_badge(wr)
        self.assertIn('Boutique', html)

    def test_status_badge(self):
        _, wallet = _make_organizer_wallet('w-st@test.com')
        wr = WithdrawalRequest.objects.create(
            wallet=wallet, amount=Decimal('1000'), fee=0, amount_net=Decimal('1000'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='X',
            status='pending',
        )
        html = self.admin.status_badge(wr)
        self.assertIn('attente', html.lower())

    def test_get_organizer(self):
        user, wallet = _make_organizer_wallet('w-getorg@test.com')
        wr = WithdrawalRequest.objects.create(
            wallet=wallet, amount=Decimal('1000'), fee=0, amount_net=Decimal('1000'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='X',
        )
        name = self.admin.get_organizer(wr)
        self.assertEqual(name, user.get_full_name())


class DisputeAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = DisputeAdmin(Dispute, self.site)
        self.admin.message_user = lambda *a, **kw: None

    def test_status_badge(self):
        d = Dispute.objects.create(
            type='refund', subject='S', description='D',
            email='d@test.com',
        )
        html = self.admin.status_badge(d)
        self.assertIn('Ouvert', html)

    def test_mark_investigating(self):
        d = Dispute.objects.create(
            type='refund', subject='S', description='D',
            email='d@test.com', status='open',
        )
        admin_user = _make_admin('adm-inv@test.com')
        self.admin.mark_investigating(
            type('R', (), {'user': admin_user})(),
            Dispute.objects.filter(pk=d.pk),
        )
        d.refresh_from_db()
        self.assertEqual(d.status, 'investigating')

    def test_mark_resolved(self):
        d = Dispute.objects.create(
            type='refund', subject='S', description='D',
            email='d@test.com', status='open',
        )
        admin_user = _make_admin('adm-res@test.com')
        self.admin.mark_resolved(
            type('R', (), {'user': admin_user})(),
            Dispute.objects.filter(pk=d.pk),
        )
        d.refresh_from_db()
        self.assertEqual(d.status, 'resolved')
        self.assertIsNotNone(d.resolved_at)

    def test_mark_closed(self):
        d = Dispute.objects.create(
            type='refund', subject='S', description='D',
            email='d@test.com', status='open',
        )
        admin_user = _make_admin('adm-cl@test.com')
        self.admin.mark_closed(
            type('R', (), {'user': admin_user})(),
            Dispute.objects.filter(pk=d.pk),
        )
        d.refresh_from_db()
        self.assertEqual(d.status, 'closed')


class AuditLogAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = AuditLogAdmin(AuditLog, self.site)

    def test_has_delete_false(self):
        self.assertFalse(self.admin.has_delete_permission(None))

    def test_has_add_false(self):
        self.assertFalse(self.admin.has_add_permission(None))

    def test_has_change_false(self):
        self.assertFalse(self.admin.has_change_permission(None))

    def test_action_badge(self):
        log = AuditLog.objects.create(
            action=AuditLog.Action.CREATE, description='X',
        )
        html = self.admin.action_badge(log)
        self.assertIn('Création', html)

    def test_description_truncated_court(self):
        log = AuditLog.objects.create(action=AuditLog.Action.OTHER, description='Court')
        self.assertEqual(self.admin.description_truncated(log), 'Court')

    def test_description_truncated_long(self):
        log = AuditLog.objects.create(
            action=AuditLog.Action.OTHER, description='X' * 200,
        )
        result = self.admin.description_truncated(log)
        self.assertTrue(result.endswith('...'))
        self.assertEqual(len(result), 103)


class WalletTransactionAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = WalletTransactionAdmin(WalletTransaction, self.site)

    def test_has_add_false(self):
        self.assertFalse(self.admin.has_add_permission(None))

    def test_has_change_false(self):
        self.assertFalse(self.admin.has_change_permission(None))

    def test_has_delete_false(self):
        self.assertFalse(self.admin.has_delete_permission(None))

    def test_wallet_organizer(self):
        # Créer un user AVEC prénom/nom
        user = CustomUser.objects.create_user(
            email='w-tx2@test.com', password='pass',
            first_name='Orga', last_name='Niseur',
        )
        user.role = CustomUser.Role.ORGANIZER
        user.save()
        wallet, _ = OrganizerWallet.objects.get_or_create(organizer=user)

        tx = WalletTransaction.objects.create(
            wallet=wallet, type=WalletTransaction.Type.CREDIT,
            amount=1000, balance_after=1000, source='events',
            reference='REF-TX-1', description='Test',
        )
        name = self.admin.wallet_organizer(tx)
        # get_full_name() retourne "Orga Niseur"
        self.assertIn('Orga', name)

    def test_wallet_organizer_sans_wallet(self):
        tx = WalletTransaction(wallet_id=None)
        self.assertEqual(self.admin.wallet_organizer(tx), '—')