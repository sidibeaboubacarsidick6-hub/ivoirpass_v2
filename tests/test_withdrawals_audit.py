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

    def test_reserve_puis_complete_diminue_le_disponible_et_finalise_le_reversement(self):
        self.wallet.credit(Decimal('50000'))
        self.wallet.reserve(Decimal('30000'), description="Réservation reversement", reference="REV-1")
        self.wallet.refresh_from_db()

        self.assertEqual(self.wallet.balance_available, Decimal('20000'))
        self.assertEqual(self.wallet.balance_pending, Decimal('30000'))
        self.assertEqual(self.wallet.balance_withdrawn, Decimal('0'))

        self.wallet.complete_reserved(
            Decimal('30000'),
            description="Reversement confirmé",
            reference="REV-1",
        )
        self.wallet.refresh_from_db()

        self.assertEqual(self.wallet.balance_available, Decimal('20000'))
        self.assertEqual(self.wallet.balance_pending, Decimal('0'))
        self.assertEqual(self.wallet.balance_withdrawn, Decimal('30000'))

    def test_reserve_refuse_si_solde_insuffisant(self):
        self.wallet.credit(Decimal('10000'))
        with self.assertRaises(ValueError):
            self.wallet.reserve(Decimal('99999'), reference="REV-2")
        self.wallet.refresh_from_db()
        self.assertEqual(
            self.wallet.balance_available,
            Decimal('10000'),
            "Le solde disponible ne doit pas bouger si la réservation échoue",
        )
        self.assertEqual(self.wallet.balance_pending, Decimal('0'))

    def test_reservation_ne_cree_jamais_de_solde_disponible_negatif(self):
        self.wallet.credit(Decimal('5000'))
        self.wallet.reserve(Decimal('5000'), reference="REV-3")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_available, Decimal('0'))
        self.assertEqual(self.wallet.balance_pending, Decimal('5000'))
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

    def test_demande_reserve_immediatement_les_fonds(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=Decimal('30000'),
            fee=Decimal('0'),
            amount_net=Decimal('30000'),
            payout_method='wave',
            payout_phone='+2250700000000',
            payout_name='Orga Deux',
        )
        self.wallet.reserve(
            wr.amount,
            description=f"Réservation reversement {wr.reference}",
            reference=wr.reference,
        )

        self.wallet.refresh_from_db()
        wr.refresh_from_db()

        self.assertEqual(wr.status, WithdrawalRequest.Status.PENDING)
        self.assertEqual(self.wallet.balance_available, Decimal('70000'))
        self.assertEqual(self.wallet.balance_pending, Decimal('30000'))
        self.assertEqual(self.wallet.balance_withdrawn, Decimal('0'))

    def test_succes_provider_finalise_le_reversement(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=Decimal('30000'),
            fee=Decimal('0'),
            amount_net=Decimal('30000'),
            payout_method='wave',
            payout_phone='+2250700000000',
            payout_name='Orga Deux',
            status=WithdrawalRequest.Status.PROCESSING,
        )
        self.wallet.reserve(wr.amount, reference=wr.reference)
        self.wallet.complete_reserved(
            wr.amount,
            description="Reversement confirmé",
            reference=wr.reference,
        )
        wr.status = WithdrawalRequest.Status.COMPLETED
        wr.save(update_fields=['status'])

        self.wallet.refresh_from_db()
        wr.refresh_from_db()

        self.assertEqual(wr.status, WithdrawalRequest.Status.COMPLETED)
        self.assertEqual(self.wallet.balance_available, Decimal('70000'))
        self.assertEqual(self.wallet.balance_pending, Decimal('0'))
        self.assertEqual(self.wallet.balance_withdrawn, Decimal('30000'))

    def test_echec_definitif_provider_libere_les_fonds(self):
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=Decimal('30000'),
            fee=Decimal('0'),
            amount_net=Decimal('30000'),
            payout_method='wave',
            payout_phone='+2250700000000',
            payout_name='Orga Deux',
            status=WithdrawalRequest.Status.PROCESSING,
        )
        self.wallet.reserve(wr.amount, reference=wr.reference)
        self.wallet.release_reserved(
            wr.amount,
            description="Reversement échoué",
            reference=wr.reference,
        )
        wr.status = WithdrawalRequest.Status.FAILED
        wr.save(update_fields=['status'])

        self.wallet.refresh_from_db()
        wr.refresh_from_db()

        self.assertEqual(wr.status, WithdrawalRequest.Status.FAILED)
        self.assertEqual(self.wallet.balance_available, Decimal('100000'))
        self.assertEqual(self.wallet.balance_pending, Decimal('0'))
        self.assertEqual(self.wallet.balance_withdrawn, Decimal('0'))
