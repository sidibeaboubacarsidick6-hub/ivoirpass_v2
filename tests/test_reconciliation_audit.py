"""
Test d'audit — Réconciliation PayDunya ↔ IvoirPass (R-04).

Couvre : récupération d'un paiement confirmé côté PayDunya mais jamais reçu
par webhook (webhook perdu), marquage échoué/annulé, non-double-traitement,
et signalement d'anomalie pour un paiement PENDING trop ancien.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_reconciliation_audit -v 2
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.core import mail
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.tickets.models import Order
from apps.payments.models import Payment
from apps.payments.tasks import reconcile_pending_payments
from apps.dashboard.models import AuditLog


class ReconciliationTaskTests(TestCase):
    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email="acheteur.recon@test.com", password="Pass123!",
            first_name="Ache", last_name="Teur",
        )

    def _make_pending_payment(self, token, created_at, amount=Decimal('10000')):
        order = Order.objects.create(
            buyer=self.buyer,
            subtotal=amount, commission=Decimal('0'), total=amount,
            status=Order.Status.PENDING,
        )
        payment = Payment.objects.create(
            order=order, amount=amount, currency='XOF',
            status=Payment.Status.PENDING,
            provider=Payment.Provider.PAYDUNYA,
            paydunya_token=token,
        )
        # created_at a auto_now_add=True : on le recule explicitement pour
        # simuler un paiement resté PENDING depuis un moment.
        Payment.objects.filter(pk=payment.pk).update(created_at=created_at)
        payment.refresh_from_db()
        return order, payment

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_paiement_confirme_chez_paydunya_mais_jamais_recu_est_recupere(self, mock_verify):
        """Le cas central de R-04 : webhook jamais arrivé, PayDunya dit pourtant 'completed'."""
        mock_verify.return_value = {'success': True, 'status': 'completed'}
        order, payment = self._make_pending_payment(
            'tok_recon_1', created_at=timezone.now() - timedelta(minutes=30)
        )

        reconcile_pending_payments()

        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID, "La commande doit être rattrapée par la réconciliation")
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.RECONCILIATION_RECOVERED).exists(),
            "Une entrée d'audit doit tracer la récupération",
        )

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_paiement_deja_confirme_par_ailleurs_nest_pas_retraite(self, mock_verify):
        """Si la commande a déjà été confirmée entre-temps (webhook arrivé juste avant), pas de double traitement."""
        mock_verify.return_value = {'success': True, 'status': 'completed'}
        order, payment = self._make_pending_payment(
            'tok_recon_2', created_at=timezone.now() - timedelta(minutes=30)
        )
        # Simule une confirmation concurrente juste avant l'exécution de la tâche.
        order.mark_as_paid(payment_method='paydunya', payment_reference='tok_recon_2')

        reconcile_pending_payments()

        self.assertFalse(
            AuditLog.objects.filter(action=AuditLog.Action.RECONCILIATION_RECOVERED).exists(),
            "Pas de log de récupération si la commande était déjà payée",
        )

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_paiement_echoue_chez_paydunya_est_marque_echoue(self, mock_verify):
        mock_verify.return_value = {'success': False, 'status': 'failed'}
        order, payment = self._make_pending_payment(
            'tok_recon_3', created_at=timezone.now() - timedelta(minutes=30)
        )

        reconcile_pending_payments()

        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(order.status, Order.Status.PENDING, "La commande elle-même n'est pas modifiée sur un échec")

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_paiement_trop_recent_nest_pas_verifie(self, mock_verify):
        """Un paiement de moins de 15 minutes ne doit pas être interrogé (laisse le temps au flux normal)."""
        self._make_pending_payment('tok_recon_4', created_at=timezone.now())

        reconcile_pending_payments()

        mock_verify.assert_not_called()

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_paiement_pending_tres_ancien_est_signale_en_anomalie(self, mock_verify):
        mock_verify.return_value = {'success': True, 'status': 'pending'}
        self._make_pending_payment(
            'tok_recon_5', created_at=timezone.now() - timedelta(hours=72)
        )

        reconcile_pending_payments()

        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.RECONCILIATION_ANOMALY).exists(),
            "Un paiement PENDING depuis plus de 48h doit être signalé",
        )

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_anomalie_declenche_une_alerte_email_aux_admins(self, mock_verify):
        admin = CustomUser.objects.create_user(
            email='admin.recon@test.com', password='Pass123!',
            role=CustomUser.Role.ADMIN, notify_email=True,
        )
        mock_verify.return_value = {'success': True, 'status': 'pending'}
        self._make_pending_payment(
            'tok_recon_6', created_at=timezone.now() - timedelta(hours=72)
        )

        reconcile_pending_payments()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('anomalie', mail.outbox[0].subject.lower())
        self.assertIn(admin.email, mail.outbox[0].to)

    @patch('apps.payments.paydunya.PayDunyaService.verify_payment')
    def test_pas_danomalie_pas_demail(self, mock_verify):
        """Le cas normal (récupération réussie) ne doit pas déclencher d'alerte."""
        CustomUser.objects.create_user(
            email='admin.recon2@test.com', password='Pass123!',
            role=CustomUser.Role.ADMIN, notify_email=True,
        )
        mock_verify.return_value = {'success': True, 'status': 'completed'}
        self._make_pending_payment(
            'tok_recon_7', created_at=timezone.now() - timedelta(minutes=30)
        )

        reconcile_pending_payments()

        self.assertEqual(len(mail.outbox), 0)
