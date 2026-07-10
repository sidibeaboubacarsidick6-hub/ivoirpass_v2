"""
Test d'audit — Wallet & Reversements (argent qui sort de la plateforme).
Couvre : credit/debit du wallet, cycle approve/mark_processed/reject,
et le bug connu d'incohérence si le débit échoue après le changement de statut.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_withdrawals_audit -v 2
"""
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings

from apps.accounts.models import CustomUser
from apps.dashboard.models import OrganizerWallet, WithdrawalRequest, WalletTransaction
from apps.notifications.models import AdminNotification


class WalletCreditDebitTests(TestCase):

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email="orga@test.com", password="Pass123!",
            first_name="Orga", last_name="Nisateur", role=CustomUser.Role.ORGANIZER,
        )
        self.wallet = OrganizerWallet.objects.create(organizer=self.organizer, balance_available=Decimal('0'))

    def test_credit_augmente_le_solde_et_trace_la_transaction(self):
        self.wallet.credit(Decimal('20000'), description="Vente billet", reference="ORD-1")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_available, Decimal('20000'))
        tx = WalletTransaction.objects.filter(wallet=self.wallet, type=WalletTransaction.Type.CREDIT).latest('created_at')
        self.assertEqual(tx.amount, Decimal('20000'))
        self.assertEqual(tx.balance_after, Decimal('20000'))

    def test_debit_diminue_le_solde_et_trace_la_transaction(self):
        self.wallet.credit(Decimal('50000'))
        self.wallet.debit(Decimal('30000'), description="Reversement", reference="REV-1")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_available, Decimal('20000'))
        self.assertEqual(self.wallet.balance_withdrawn, Decimal('30000'))

    def test_debit_refuse_si_solde_insuffisant(self):
        self.wallet.credit(Decimal('10000'))
        with self.assertRaises(ValueError):
            self.wallet.debit(Decimal('99999'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_available, Decimal('10000'), "Le solde ne doit pas bouger si le débit échoue")

    def test_pas_de_solde_negatif_apres_debit_refuse(self):
        self.wallet.credit(Decimal('5000'))
        try:
            self.wallet.debit(Decimal('5001'))
        except ValueError:
            pass
        self.wallet.refresh_from_db()
        self.assertGreaterEqual(self.wallet.balance_available, Decimal('0'))


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class WithdrawalRequestLifecycleTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            email="admin@ivoirpass.test", password="Pass123!",
            first_name="Admin", last_name="Test", role=CustomUser.Role.ADMIN,
            is_active=True, is_staff=True, notify_email=True,
        )
        self.organizer = CustomUser.objects.create_user(
            email="orga2@test.com", password="Pass123!",
            first_name="Orga", last_name="Deux", role=CustomUser.Role.ORGANIZER,
        )
        self.wallet = OrganizerWallet.objects.create(organizer=self.organizer, balance_available=Decimal('100000'))

    def test_creation_demande_notifie_admin_par_email(self):
        mail.outbox.clear()
        WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=Decimal('40000'), fee=Decimal('1000'),
            amount_net=Decimal('39000'), payout_method='wave',
            payout_phone='+2250700000000', payout_name='Orga Deux',
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("40000", mail.outbox[0].body)

    def test_approve_ne_debite_pas_encore_le_wallet(self):
        """approve() change le statut mais ne doit débiter qu'à mark_processed()."""
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=Decimal('30000'), fee=Decimal('0'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='Orga Deux',
        )
        wr.approve(self.admin, note="OK")
        self.wallet.refresh_from_db()
        self.assertEqual(wr.status, WithdrawalRequest.Status.APPROVED)
        self.assertEqual(self.wallet.balance_available, Decimal('100000'), "Le solde ne doit pas bouger à l'approbation seule")

    def test_mark_processed_debite_effectivement_le_wallet(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=Decimal('30000'), fee=Decimal('0'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='Orga Deux',
        )
        wr.approve(self.admin)
        mail.outbox.clear()
        wr.mark_processed(self.admin, note="Viré")
        self.wallet.refresh_from_db()
        wr.refresh_from_db()
        self.assertEqual(wr.status, WithdrawalRequest.Status.PROCESSED)
        self.assertEqual(self.wallet.balance_available, Decimal('70000'))
        self.assertEqual(len(mail.outbox), 1, "L'organisateur doit recevoir un email de confirmation")
        self.assertEqual(mail.outbox[0].to, ["orga2@test.com"])

    def test_reject_ne_touche_jamais_au_solde(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=Decimal('30000'), fee=Decimal('0'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='Orga Deux',
        )
        wr.reject(self.admin, note="Coordonnées invalides")
        self.wallet.refresh_from_db()
        self.assertEqual(wr.status, WithdrawalRequest.Status.REJECTED)
        self.assertEqual(self.wallet.balance_available, Decimal('100000'))

    def test_mark_processed_reste_coherent_si_debit_echoue(self):
        """
        Non-régression : mark_processed() débite le wallet AVANT de figer
        le statut PROCESSED (dans une transaction atomique). Si le débit
        échoue (solde insuffisant), la demande doit rester dans son statut
        précédent, PAS PROCESSED — pour ne jamais afficher un reversement
        comme "traité" alors que l'argent n'a jamais bougé.
        """
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=Decimal('30000'), fee=Decimal('0'),
            payout_method='wave', payout_phone='+2250700000000', payout_name='Orga Deux',
        )
        wr.approve(self.admin)

        # Le solde chute en dessous du montant demandé avant le traitement
        # (ex : un autre reversement concurrent vient d'être traité)
        self.wallet.balance_available = Decimal('10000')
        self.wallet.save(update_fields=['balance_available'])

        with self.assertRaises(ValueError):
            wr.mark_processed(self.admin, note="Viré")

        wr.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            wr.status, WithdrawalRequest.Status.APPROVED,
            "La demande ne doit PAS passer à PROCESSED si le débit a échoué"
        )
        self.assertEqual(
            self.wallet.balance_withdrawn, Decimal('0'),
            "Aucun montant ne doit être compté comme reversé si le débit a échoué"
        )
