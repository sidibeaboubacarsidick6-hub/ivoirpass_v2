"""
Tests du Dashboard et Wallet
"""
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import CustomUser
from apps.dashboard.models import OrganizerWallet, WalletTransaction, WithdrawalRequest


class WalletModelTest(TestCase):
    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )

    def test_wallet_created_automatically(self):
        wallet, created = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )
        self.assertEqual(wallet.balance_available, 0)
        self.assertEqual(wallet.balance_pending, 0)

    def test_wallet_credit(self):
        wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )
        wallet.credit(10000, description='Vente ticket', reference='IP-2026-ABC')
        self.assertEqual(wallet.balance_available, 10000)
        self.assertEqual(wallet.transactions.count(), 1)

    def test_wallet_debit(self):
        wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )
        wallet.credit(20000, description='Vente')
        wallet.debit(5000, description='Reversement', reference='REV-001')
        self.assertEqual(wallet.balance_available, 15000)
        self.assertEqual(wallet.balance_withdrawn, 5000)

    def test_wallet_debit_insufficient(self):
        wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )
        with self.assertRaises(ValueError):
            wallet.debit(1000, description='Trop')

    def test_withdrawal_request_creation(self):
        wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )
        wallet.credit(50000, description='Ventes')
        wr = WithdrawalRequest.objects.create(
            wallet=wallet,
            amount=30000,
            payout_method='wave',
            payout_phone='+2250707070707',
            payout_name='Jean Test'
        )
        self.assertTrue(wr.reference.startswith('REV-'))
        self.assertEqual(wr.status, WithdrawalRequest.Status.PENDING)


class DashboardViewTest(TestCase):
    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com',
            password='Pass123!',
            role=CustomUser.Role.ORGANIZER
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_organizer_access(self):
        self.client.login(email='org@test.com', password='Pass123!')
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(response.status_code, 200)

    def test_wallet_page_access(self):
        self.client.login(email='org@test.com', password='Pass123!')
        response = self.client.get(reverse('dashboard:wallet'))
        self.assertEqual(response.status_code, 200)
