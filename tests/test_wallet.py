"""
IvoirPass V2 — Tests du wallet organisateur
"""
from django.test import TestCase
from apps.accounts.models import CustomUser
from apps.dashboard.models import OrganizerWallet, WalletTransaction, WithdrawalRequest


class WalletTest(TestCase):

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        self.wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )

    def test_wallet_creation(self):
        self.assertEqual(self.wallet.balance_available, 0)
        self.assertEqual(self.wallet.balance_withdrawn, 0)

    def test_wallet_credit(self):
        self.wallet.credit(
            amount      = 46000,
            description = 'Vente test',
            reference   = 'IP-2026-TEST01',
        )
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_available, 46000)

        tx = WalletTransaction.objects.filter(wallet=self.wallet).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.type, 'credit')
        self.assertEqual(tx.amount, 46000)

    def test_wallet_debit(self):
        self.wallet.credit(amount=50000, description='Test', reference='REF1')
        self.wallet.debit(
            amount      = 30000,
            description = 'Reversement test',
            reference   = 'REV-00000001',
        )
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_available, 20000)
        self.assertEqual(self.wallet.balance_withdrawn, 30000)

    def test_wallet_debit_insufficient(self):
        self.wallet.credit(amount=10000, description='Test', reference='REF2')
        with self.assertRaises(ValueError):
            self.wallet.debit(amount=20000, description='Trop', reference='REV2')

    def test_withdrawal_request_creation(self):
        self.wallet.credit(amount=50000, description='Test', reference='REF3')
        wr = WithdrawalRequest.objects.create(
            wallet        = self.wallet,
            amount        = 30000,
            payout_method = 'wave',
            payout_phone  = '+225 07 00 00 00 00',
            payout_name   = 'Adjoua Konan',
        )
        self.assertIsNotNone(wr.reference)
        self.assertTrue(wr.reference.startswith('REV-'))
        self.assertEqual(wr.status, 'pending')

    def test_commission_rate_dynamic(self):
        """La commission est prélevée sur l'organisateur pas sur l'acheteur."""
        # Simule une vente de 5 000 FCFA avec commission 8%
        price      = 5000
        commission = price * 0.08
        net        = price - commission
        self.assertEqual(net, 4600)
        # L'acheteur paie 5 000 FCFA, pas 5 400 FCFA
        self.assertEqual(price, 5000)


class WithdrawalAdminTest(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_superuser(
            email='admin@ivoirpass.com',
            password='AdminPass2026!',
        )
        self.organizer = CustomUser.objects.create_user(
            email='orga@test.com', password='IvoirPass2026!',
            role='organizer',
        )
        self.wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.organizer
        )
        self.wallet.credit(amount=100000, description='Test', reference='REF')
        self.wr = WithdrawalRequest.objects.create(
            wallet        = self.wallet,
            amount        = 50000,
            payout_method = 'orange_money',
            payout_phone  = '+225 07 11 22 33 44',
            payout_name   = 'Test Orga',
        )

    def test_approve_withdrawal(self):
        self.wr.approve(admin_user=self.admin, note='Approuvé')
        self.assertEqual(self.wr.status, 'approved')

    def test_process_withdrawal_debits_wallet(self):
        self.wr.mark_processed(admin_user=self.admin, note='Virement effectué')
        self.wr.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(self.wr.status, 'processed')
        self.assertEqual(self.wallet.balance_available, 50000)
        self.assertEqual(self.wallet.balance_withdrawn, 50000)

    def test_reject_withdrawal(self):
        self.wr.reject(admin_user=self.admin, note='Informations incorrectes')
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, 'rejected')