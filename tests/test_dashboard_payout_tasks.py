"""
Tests des tâches Celery de décaissement — apps/dashboard/tasks.py

Couvre :
- process_payout : création + soumission + succès + pending + échec + retry
- check_payout_status : succès / pending / stale (>6h) / failed / retry max
- finalize_payout_from_provider : success / failed / already_completed
- _retry_or_fail_payout : retry tant qu'il reste des essais / fail définitif
- Vérifications wallet : reserve / complete_reserved / release_reserved
"""
from decimal import Decimal
from unittest.mock import patch
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from celery.exceptions import Retry

from apps.accounts.models import CustomUser
from apps.dashboard.models import (
    OrganizerWallet, WalletTransaction, WithdrawalRequest,
)
from apps.dashboard import tasks as dashboard_tasks


def _make_organizer(email='org@test.com', balance=50000):
    u = CustomUser.objects.create_user(
        email=email, password='pass',
        first_name='Org', last_name='Test',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    wallet, _ = OrganizerWallet.objects.get_or_create(organizer=u)
    wallet.balance_events_available = Decimal(str(balance))
    wallet.save(update_fields=['balance_events_available'])
    return u, wallet


def _make_withdrawal(wallet, amount=5000, source='events'):
    """Crée une demande de reversement réservée (comme le fait withdraw_request)."""
    wr = WithdrawalRequest.objects.create(
        wallet=wallet,
        amount=Decimal(str(amount)),
        fee=0,
        amount_net=Decimal(str(amount)),
        payout_method='wave',
        payout_phone='+2250700000000',
        payout_name='Org Test',
        source=source,
        status=WithdrawalRequest.Status.PROCESSING,
    )
    wallet.reserve(
        Decimal(str(amount)),
        source=source,
        description=f"Réservation reversement {wr.reference}",
        reference=wr.reference,
    )
    return wr


class ProcessPayoutTests(TestCase):
    """Tests de la tâche process_payout."""

    def setUp(self):
        self.org, self.wallet = _make_organizer()
        self.wr = _make_withdrawal(self.wallet, amount=5000)

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_process_payout_statut_deja_terminal(self, mock_service):
        """Si le retrait est déjà COMPLETED → on ne fait rien."""
        self.wr.status = WithdrawalRequest.Status.COMPLETED
        self.wr.save(update_fields=['status'])

        result = dashboard_tasks.process_payout(self.wr.pk)

        self.assertEqual(result, WithdrawalRequest.Status.COMPLETED)
        mock_service.create_disbursement.assert_not_called()

    @patch('apps.payments.paydunya.PayDunyaService')
    @patch('apps.dashboard.tasks.finalize_payout_from_provider')
    def test_process_payout_create_et_submit_success(self, mock_finalize, mock_service):
        """Création + soumission + succès → finalize appelé."""
        mock_service.create_disbursement.return_value = {
            'success': True, 'token': 'tok_123', 'status': 'created',
        }
        mock_service.submit_disbursement.return_value = {
            'success': True, 'status': 'success',
            'transaction_id': 'tx_abc', 'provider_ref': 'ref_xyz',
        }
        mock_finalize.return_value = 'completed'

        result = dashboard_tasks.process_payout(self.wr.pk)

        self.assertEqual(result, 'completed')
        mock_service.create_disbursement.assert_called_once()
        mock_service.submit_disbursement.assert_called_once()
        mock_finalize.assert_called_once()

        self.wr.refresh_from_db()
        self.assertEqual(self.wr.provider_token, 'tok_123')

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_process_payout_create_echoue_retry(self, mock_service):
        """Création échoue → Retry levé (comportement Celery normal)."""
        mock_service.create_disbursement.return_value = {
            'success': False, 'error': 'Erreur réseau PayDunya',
        }

        # Le code lève volontairement Retry pour relancer la tâche
        with self.assertRaises(Retry):
            dashboard_tasks.process_payout(self.wr.pk)

        # Le statut a bien été mis à jour avant le raise
        self.wr.refresh_from_db()
        self.assertEqual(self.wr.provider_status, 'failed')
        self.assertIn('Erreur réseau', self.wr.last_error)

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_process_payout_pending_planifie_check(self, mock_service):
        """Soumission pending → statut reste pending + replanification."""
        mock_service.create_disbursement.return_value = {
            'success': True, 'token': 'tok_pending',
        }
        mock_service.submit_disbursement.return_value = {
            'success': True, 'status': 'pending',
        }

        with patch.object(
            dashboard_tasks.check_payout_status, 'apply_async'
        ) as mock_apply:
            result = dashboard_tasks.process_payout(self.wr.pk)

            self.assertEqual(result, 'pending')
            mock_apply.assert_called_once()

        self.wr.refresh_from_db()
        self.assertEqual(self.wr.provider_status, 'pending')

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_process_payout_token_deja_present_skip_create(self, mock_service):
        """Si provider_token existe déjà, on ne recrée pas."""
        self.wr.provider_token = 'tok_existing'
        self.wr.save(update_fields=['provider_token'])

        mock_service.submit_disbursement.return_value = {
            'success': True, 'status': 'success',
        }
        mock_service.check_disbursement_status.return_value = {
            'status': 'success', 'success': True,
        }

        dashboard_tasks.process_payout(self.wr.pk)

        mock_service.create_disbursement.assert_not_called()


class CheckPayoutStatusTests(TestCase):
    """Tests de la tâche check_payout_status."""

    def setUp(self):
        self.org, self.wallet = _make_organizer()
        self.wr = _make_withdrawal(self.wallet, amount=5000)
        self.wr.provider_token = 'tok_xyz'
        self.wr.save(update_fields=['provider_token'])

    def test_check_payout_status_demande_introuvable(self):
        """ID inexistant → 'not_found'."""
        result = dashboard_tasks.check_payout_status(999999)
        self.assertEqual(result, 'not_found')

    def test_check_payout_status_deja_completed(self):
        """Statut COMPLETED → on ne fait rien."""
        self.wr.status = WithdrawalRequest.Status.COMPLETED
        self.wr.save(update_fields=['status'])

        result = dashboard_tasks.check_payout_status(self.wr.pk)
        self.assertEqual(result, WithdrawalRequest.Status.COMPLETED)

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_check_payout_status_success(self, mock_service):
        """PayDunya retourne success → wallet débité + statut COMPLETED."""
        mock_service.check_disbursement_status.return_value = {
            'status': 'success', 'success': True,
            'transaction_id': 'tx_ok',
        }

        result = dashboard_tasks.check_payout_status(self.wr.pk)

        # finalize_payout_from_provider a réellement été exécuté
        # → le wallet doit être débité
        self.assertEqual(result, 'completed')
        self.wr.refresh_from_db()
        self.wr.wallet.refresh_from_db()
        self.assertEqual(self.wr.status, WithdrawalRequest.Status.COMPLETED)
        self.assertEqual(self.wr.wallet.balance_events_pending, 0)
        self.assertEqual(self.wr.wallet.balance_withdrawn, 5000)

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_check_payout_status_pending_replanifie(self, mock_service):
        """PayDunya pending → statut mis à jour + replanification."""
        mock_service.check_disbursement_status.return_value = {
            'status': 'pending', 'success': True,
        }

        with patch.object(
            dashboard_tasks.check_payout_status, 'apply_async'
        ) as mock_apply:
            result = dashboard_tasks.check_payout_status(self.wr.pk)

            self.assertEqual(result, 'pending')
            mock_apply.assert_called_once()

        self.wr.refresh_from_db()
        self.assertEqual(self.wr.provider_status, 'pending')

    @patch('apps.payments.paydunya.PayDunyaService')
    def test_check_payout_status_stale_plus_de_6h(self, mock_service):
        """Demande > 6h en attente → arrêt + log d'anomalie."""
        # Simule une demande créée il y a 8h
        old_date = timezone.now() - timedelta(hours=8)
        WithdrawalRequest.objects.filter(pk=self.wr.pk).update(created_at=old_date)
        self.wr.refresh_from_db()

        result = dashboard_tasks.check_payout_status(self.wr.pk)

        self.assertEqual(result, 'stale')
        mock_service.check_disbursement_status.assert_not_called()

    @patch('apps.payments.paydunya.PayDunyaService')
    @patch('apps.dashboard.tasks.process_payout')
    def test_check_payout_status_pas_de_token_requeue(self, mock_process, mock_service):
        """Pas de provider_token → process_payout relancé."""
        self.wr.provider_token = ''
        self.wr.save(update_fields=['provider_token'])

        result = dashboard_tasks.check_payout_status(self.wr.pk)

        self.assertEqual(result, 'requeued')
        mock_process.delay.assert_called_once()


class FinalizePayoutFromProviderTests(TestCase):
    """Tests de la tâche finalize_payout_from_provider."""

    def setUp(self):
        self.org, self.wallet = _make_organizer()
        self.wr = _make_withdrawal(self.wallet, amount=5000)

    def test_finalize_introuvable(self):
        result = dashboard_tasks.finalize_payout_from_provider(999999, {})
        self.assertEqual(result, 'not_found')

    def test_finalize_success_debite_wallet(self):
        """Payload success → wallet débité (complete_reserved)."""
        # Solde en attente = 5000 (réservé)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_pending, 5000)

        payload = {'status': 'success', 'transaction_id': 'tx_ok'}
        result = dashboard_tasks.finalize_payout_from_provider(self.wr.pk, payload)

        self.assertEqual(result, 'completed')

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_events_pending, 0)
        self.assertEqual(self.wallet.balance_withdrawn, 5000)

        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, WithdrawalRequest.Status.COMPLETED)
        self.assertIsNotNone(self.wr.completed_at)

    def test_finalize_already_completed(self):
        """Si déjà COMPLETED → pas de double débit."""
        self.wr.status = WithdrawalRequest.Status.COMPLETED
        self.wr.save(update_fields=['status'])

        wallet_before = self.wallet.balance_withdrawn
        result = dashboard_tasks.finalize_payout_from_provider(
            self.wr.pk, {'status': 'success'}
        )

        self.assertEqual(result, 'already_completed')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance_withdrawn, wallet_before)

    @patch('apps.dashboard.tasks.process_payout')
    def test_finalize_failed_retry_si_sous_max(self, mock_process):
        """Payload failed + retry_count < 3 → retry."""
        payload = {'status': 'failed', 'error': 'Solde insuffisant Orange'}
        result = dashboard_tasks.finalize_payout_from_provider(self.wr.pk, payload)

        self.assertEqual(result, 'retrying')
        mock_process.apply_async.assert_called_once()

    @patch('apps.dashboard.tasks.process_payout')
    def test_finalize_failed_definitif_release_wallet(self, mock_process):
        """Payload failed + retry_count >= 3 → release wallet + FAILED."""
        self.wr.retry_count = 3
        self.wr.save(update_fields=['retry_count'])

        payload = {'status': 'failed', 'error': 'Échec définitif'}

        result = dashboard_tasks.finalize_payout_from_provider(self.wr.pk, payload)

        self.assertEqual(result, 'failed')

        self.wallet.refresh_from_db()
        # Le montant réservé est libéré vers dispo
        self.assertEqual(self.wallet.balance_events_pending, 0)
        self.assertEqual(self.wallet.balance_events_available, 50000)

        self.wr.refresh_from_db()
        self.assertEqual(self.wr.status, WithdrawalRequest.Status.FAILED)


class CheckPendingWithdrawalsTests(TestCase):
    """Tests de la tâche check_pending_withdrawals (alerte admin)."""

    def setUp(self):
        self.org, self.wallet = _make_organizer()

    @patch('apps.dashboard.tasks.send_mail')
    def test_aucun_reversement_en_retard(self, mock_send):
        result = dashboard_tasks.check_pending_withdrawals()
        self.assertIn('Aucun', result)
        mock_send.assert_not_called()

    @patch('apps.dashboard.tasks.send_mail')
    def test_reversement_en_retard_alerte_admin(self, mock_send):
        """Créer un retrait PENDING depuis > 24h → alerte envoyée."""
        admin = CustomUser.objects.create_user(
            email='admin@test.com', password='pass',
        )
        admin.role = CustomUser.Role.ADMIN
        admin.notify_email = True
        admin.save()

        wr = _make_withdrawal(self.wallet, amount=5000)
        wr.status = WithdrawalRequest.Status.PENDING
        wr.save(update_fields=['status'])
        # Anti-date la création à 30h
        old = timezone.now() - timedelta(hours=30)
        WithdrawalRequest.objects.filter(pk=wr.pk).update(created_at=old)

        result = dashboard_tasks.check_pending_withdrawals()

        self.assertIn('reversement', result.lower())
        mock_send.assert_called_once()