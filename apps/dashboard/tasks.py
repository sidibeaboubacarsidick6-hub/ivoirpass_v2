"""
IvoirPass V2 — Tâches Celery pour le dashboard
"""
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Sum

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def check_pending_withdrawals(self):
    """
    Vérifie les demandes de reversement en attente depuis plus de 24h.
    Envoie une alerte aux admins si trouvé.
    """
    from .models import WithdrawalRequest
    from apps.accounts.models import CustomUser

    deadline = timezone.now() - timedelta(hours=24)

    pending = WithdrawalRequest.objects.filter(
        status=WithdrawalRequest.Status.PENDING,
        created_at__lte=deadline,
    )

    count = pending.count()
    if count == 0:
        logger.info("Aucun reversement en retard.")
        return "Aucun reversement en retard."

    # Lister les demandes
    details = []
    for wr in pending:
        hours = int((timezone.now() - wr.created_at).total_seconds() / 3600)
        details.append(
            f"- {wr.reference} : {wr.amount} FCFA "
            f"({wr.wallet.organizer.get_full_name()}) "
            f"— en attente depuis {hours}h"
        )

    message = (
        f"⚠️ {count} demande(s) de reversement en attente depuis plus de 24h :\n\n"
        + "\n".join(details)
        + "\n\nVeuillez traiter ces demandes dans le back-office."
    )

    # Envoyer aux admins
    admins = CustomUser.objects.filter(
        role=CustomUser.Role.ADMIN,
        is_active=True,
        notify_email=True,
    )

    if admins.exists():
        recipient_list = list(admins.values_list('email', flat=True))
        send_mail(
            subject='[IvoirPass] ⚠️ Reversements en retard',
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
        logger.info(f"Alerte envoyée à {len(recipient_list)} admin(s)")

    return f"{count} reversement(s) en retard — admins notifiés"

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_payout(self, withdrawal_id):
    """Initie/soumet un payout PayDunya sans jamais débiter deux fois le wallet."""
    from django.db import transaction
    from .models import WithdrawalRequest, AuditLog
    from .services import log_action
    from apps.payments.paydunya import PayDunyaService

    try:
        with transaction.atomic():
            withdrawal = WithdrawalRequest.objects.select_for_update().select_related('wallet__organizer').get(pk=withdrawal_id)
            if withdrawal.status in [WithdrawalRequest.Status.COMPLETED, WithdrawalRequest.Status.CANCELLED, WithdrawalRequest.Status.REJECTED]:
                return withdrawal.status
            if withdrawal.status == WithdrawalRequest.Status.PENDING:
                withdrawal.status = WithdrawalRequest.Status.PROCESSING
                withdrawal.save(update_fields=['status'])
            token = withdrawal.provider_token
            reference = withdrawal.reference

        if not token:
            result = PayDunyaService.create_disbursement(withdrawal)
            if not result.get('success'):
                return _retry_or_fail_payout(self, withdrawal_id, result.get('error', 'Erreur initiation payout'))
            token = result['token']
            with transaction.atomic():
                current = WithdrawalRequest.objects.select_for_update().get(pk=withdrawal_id)
                if current.status == WithdrawalRequest.Status.COMPLETED:
                    return 'completed'
                current.provider_token = token
                current.provider_status = 'created'
                current.save(update_fields=['provider_token', 'provider_status'])
            log_action(AuditLog.Action.PAYOUT_INITIATED, f"Reversement {reference} initié auprès de PayDunya", obj=withdrawal, metadata={'amount': str(withdrawal.amount), 'payout_method': withdrawal.payout_method})

        result = PayDunyaService.submit_disbursement(token, reference)
        status = (result.get('status') or '').lower()
        if status == 'success':
            result['status'] = 'success'
            finalize_payout_from_provider(withdrawal_id, result)
            return 'completed'
        if status == 'pending':
            WithdrawalRequest.objects.filter(pk=withdrawal_id).update(provider_status='pending')
            log_action(AuditLog.Action.PAYOUT_PROVIDER_PENDING, f"Reversement {reference} en attente chez PayDunya", obj=withdrawal, metadata={'amount': str(withdrawal.amount)})
            check_payout_status.apply_async(args=[withdrawal_id], countdown=120)
            return 'pending'

        # En cas de réponse ambiguë/erreur de submit, on vérifie d'abord le token existant
        # avant de créer un nouveau payout.
        if token:
            status_check = PayDunyaService.check_disbursement_status(token)
            checked = (status_check.get('status') or '').lower()
            if checked == 'success':
                finalize_payout_from_provider(withdrawal_id, status_check)
                return 'completed'
            if checked == 'pending':
                WithdrawalRequest.objects.filter(pk=withdrawal_id).update(provider_status='pending')
                check_payout_status.apply_async(args=[withdrawal_id], countdown=120)
                return 'pending'
            if checked == 'created':
                return _retry_or_fail_payout(self, withdrawal_id, result.get('error') or result.get('response_text') or 'Payout encore non soumis')

        return _retry_or_fail_payout(self, withdrawal_id, result.get('error') or result.get('response_text') or 'Payout échoué')
    except WithdrawalRequest.DoesNotExist:
        return 'not_found'


def _retry_or_fail_payout(task, withdrawal_id, error):
    from django.db import transaction
    from .models import WithdrawalRequest, AuditLog
    from .services import log_action
    with transaction.atomic():
        withdrawal = WithdrawalRequest.objects.select_for_update().select_related('wallet').get(pk=withdrawal_id)
        withdrawal.last_error = str(error)[:4000]
        withdrawal.retry_count = task.request.retries + 1
        withdrawal.provider_status = 'failed'
        withdrawal.save(update_fields=['last_error', 'retry_count', 'provider_status'])
        reference = withdrawal.reference
        amount = withdrawal.amount
    log_action(AuditLog.Action.PAYOUT_FAILED, f"Reversement {reference} échoué", obj=withdrawal, metadata={'amount': str(amount), 'error': str(error)[:500]})
    if task.request.retries < task.max_retries:
        countdown = min(300, 60 * (2 ** task.request.retries))
        log_action(AuditLog.Action.PAYOUT_RETRY, f"Retry automatique du reversement {reference}", obj=withdrawal, metadata={'amount': str(amount), 'retry_count': task.request.retries + 1})
        raise task.retry(countdown=countdown)
    with transaction.atomic():
        withdrawal = WithdrawalRequest.objects.select_for_update().select_related('wallet').get(pk=withdrawal_id)
        if withdrawal.status != WithdrawalRequest.Status.COMPLETED:
            withdrawal.wallet.release_reserved(amount, source=withdrawal.source, description=f"Libération après échec définitif {reference}", reference=reference)
            withdrawal.status = WithdrawalRequest.Status.FAILED
            withdrawal.save(update_fields=['status'])
    return 'failed'


# Plafond de relance pour les reversements bloqués en "pending" chez PayDunya.
# Au-delà, on arrête de relancer la vérification pour ne pas saturer la queue
# Celery, et on laisse un humain prendre le relais. Le webhook PayDunya reste
# actif et peut confirmer le reversement à tout moment.
MAX_PENDING_HOURS = 6


@shared_task
def check_payout_status(withdrawal_id):
    from .models import WithdrawalRequest, AuditLog
    from .services import log_action
    from apps.payments.paydunya import PayDunyaService

    try:
        withdrawal = WithdrawalRequest.objects.select_related('wallet').get(pk=withdrawal_id)
    except WithdrawalRequest.DoesNotExist:
        return 'not_found'

    if withdrawal.status in [
        WithdrawalRequest.Status.COMPLETED,
        WithdrawalRequest.Status.CANCELLED,
        WithdrawalRequest.Status.REJECTED,
    ]:
        return withdrawal.status

    # 🛡️ Garde-fou : si la demande est en attente depuis trop longtemps
    # (opérateur MTN/Moov qui traîne, ou PayDunya bloqué), on arrête de
    # relancer et on signale le cas pour traitement humain.
    age = timezone.now() - withdrawal.created_at
    if age > timedelta(hours=MAX_PENDING_HOURS):
        logger.warning(
            "Reversement %s en attente depuis %.1fh — arrêt des relances, "
            "intervention manuelle requise.",
            withdrawal.reference,
            age.total_seconds() / 3600,
        )
        log_action(
            action=AuditLog.Action.PAYOUT_PROVIDER_PENDING,
            description=(
                f"Reversement {withdrawal.reference} bloqué en attente depuis "
                f"plus de {MAX_PENDING_HOURS}h — vérification manuelle requise."
            ),
            obj=withdrawal,
            metadata={
                'amount': str(withdrawal.amount),
                'provider_status': withdrawal.provider_status,
                'age_hours': round(age.total_seconds() / 3600, 1),
            },
        )
        return 'stale'

    if not withdrawal.provider_token:
        process_payout.delay(withdrawal.pk)
        return 'requeued'

    result = PayDunyaService.check_disbursement_status(withdrawal.provider_token)
    status = (result.get('status') or '').lower()

    if status == 'success':
        finalize_payout_from_provider(withdrawal.pk, result)
        return 'completed'

    if status == 'pending':
        withdrawal.provider_status = 'pending'
        withdrawal.save(update_fields=['provider_status'])
        check_payout_status.apply_async(args=[withdrawal.pk], countdown=180)
        return 'pending'

    if status == 'created':
        process_payout.delay(withdrawal.pk)
        return 'created'

    withdrawal.provider_status = 'failed'
    withdrawal.last_error = result.get('error') or result.get('response_text') or 'Payout échoué'
    withdrawal.retry_count += 1
    withdrawal.save(update_fields=['provider_status', 'last_error', 'retry_count'])
    log_action(
        AuditLog.Action.PAYOUT_FAILED,
        f"Reversement {withdrawal.reference} échoué après vérification",
        obj=withdrawal,
        metadata={'amount': str(withdrawal.amount), 'error': withdrawal.last_error},
    )
    if withdrawal.retry_count <= 3:
        process_payout.apply_async(
            args=[withdrawal.pk],
            countdown=min(300, 60 * (2 ** (withdrawal.retry_count - 1))),
        )
        return 'retrying'

    withdrawal.wallet.release_reserved(
        withdrawal.amount,
        source=withdrawal.source,
        description=f"Libération après échec payout {withdrawal.reference}",
        reference=withdrawal.reference,
    )
    withdrawal.status = WithdrawalRequest.Status.FAILED
    withdrawal.save(update_fields=['status'])
    return 'failed'


@shared_task
def finalize_payout_from_provider(withdrawal_id, payload):
    from django.db import transaction
    from .models import WithdrawalRequest, AuditLog
    from .services import log_action
    try:
        with transaction.atomic():
            withdrawal = WithdrawalRequest.objects.select_for_update().select_related('wallet').get(pk=withdrawal_id)
            if withdrawal.status == WithdrawalRequest.Status.COMPLETED:
                return 'already_completed'
            status = (payload.get('status') or '').lower()
            withdrawal.provider_status = status
            withdrawal.provider_transaction_id = payload.get('transaction_id', '') or payload.get('disburse_tx_id', '')
            withdrawal.provider_reference = payload.get('disburse_tx_id', '') or payload.get('provider_ref', '')
            if status == 'success':
                withdrawal.wallet.complete_reserved(withdrawal.amount, source=withdrawal.source, description=f"Reversement PayDunya {withdrawal.reference}", reference=withdrawal.reference)
                withdrawal.status = WithdrawalRequest.Status.COMPLETED
                withdrawal.completed_at = timezone.now()
                withdrawal.processed_at = withdrawal.completed_at
                withdrawal.save(update_fields=['provider_status', 'provider_transaction_id', 'provider_reference', 'status', 'completed_at', 'processed_at'])
                log_action(AuditLog.Action.PAYOUT_SUCCESS, f"Reversement {withdrawal.reference} confirmé par PayDunya", obj=withdrawal, metadata={'amount': str(withdrawal.amount), 'payout_method': withdrawal.payout_method})
                return 'completed'
            if status == 'failed':
                withdrawal.last_error = payload.get('error') or payload.get('response_text') or 'PayDunya a refusé le reversement'
                withdrawal.retry_count += 1
                withdrawal.save(update_fields=['provider_status', 'provider_transaction_id', 'provider_reference', 'last_error', 'retry_count'])
                if withdrawal.retry_count <= 3:
                    log_action(AuditLog.Action.PAYOUT_RETRY, f"Retry du reversement {withdrawal.reference}", obj=withdrawal, metadata={'amount': str(withdrawal.amount), 'retry_count': withdrawal.retry_count})
                    process_payout.apply_async(args=[withdrawal.pk], countdown=min(300, 60 * (2 ** (withdrawal.retry_count - 1))))
                    return 'retrying'
                withdrawal.wallet.release_reserved(withdrawal.amount, source=withdrawal.source, description=f"Libération après échec définitif {withdrawal.reference}", reference=withdrawal.reference)
                withdrawal.status = WithdrawalRequest.Status.FAILED
                withdrawal.save(update_fields=['status'])
                log_action(AuditLog.Action.PAYOUT_FAILED, f"Reversement {withdrawal.reference} définitivement échoué", obj=withdrawal, metadata={'amount': str(withdrawal.amount), 'error': withdrawal.last_error})
                return 'failed'
            withdrawal.save(update_fields=['provider_status', 'provider_transaction_id', 'provider_reference'])
            return status or 'unknown'
    except WithdrawalRequest.DoesNotExist:
        return 'not_found'


@shared_task(bind=True)
def generate_bceao_report(self):
    """
    Génère un rapport mensuel pour la BCEAO.
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.tickets.models import Order, GuestOrder
    from apps.store.models import ProductOrder, GuestProductOrder
    from apps.dashboard.models import WithdrawalRequest, OrganizerWallet
    from apps.accounts.models import CustomUser
    from django.core.mail import send_mail
    from django.conf import settings
    import io

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0)

    # Nombre de transactions — couvre les commandes "avec compte" ET
    # invité. La boutique ne vend aujourd'hui qu'en achat invité : ignorer
    # GuestOrder/GuestProductOrder ferait apparaître un rapport quasiment
    # vide alors que l'activité réelle est bien là.
    ticket_orders_account = Order.objects.filter(paid_at__gte=month_start, status='paid').count()
    ticket_orders_guest = GuestOrder.objects.filter(paid_at__gte=month_start, status='paid').count()
    ticket_orders = ticket_orders_account + ticket_orders_guest

    store_orders_account = ProductOrder.objects.filter(paid_at__gte=month_start, status='paid').count()
    store_orders_guest = GuestProductOrder.objects.filter(paid_at__gte=month_start, status='paid').count()
    store_orders = store_orders_account + store_orders_guest

    # Volume financier
    ticket_volume_account = Order.objects.filter(paid_at__gte=month_start, status='paid').aggregate(
        total=Sum('total')
    )['total'] or 0
    ticket_volume_guest = GuestOrder.objects.filter(paid_at__gte=month_start, status='paid').aggregate(
        total=Sum('total')
    )['total'] or 0
    ticket_volume = ticket_volume_account + ticket_volume_guest

    store_volume_account = ProductOrder.objects.filter(paid_at__gte=month_start, status='paid').aggregate(
        total=Sum('total')
    )['total'] or 0
    store_volume_guest = GuestProductOrder.objects.filter(paid_at__gte=month_start, status='paid').aggregate(
        total=Sum('total')
    )['total'] or 0
    store_volume = store_volume_account + store_volume_guest

    # Commissions (billetterie — compte + invité)
    ticket_commission = sum(
        float(o.total) * float(o.items.first().ticket_type.event.commission_rate) / 100
        for o in Order.objects.filter(paid_at__gte=month_start, status='paid').prefetch_related('items__ticket_type__event')
        if o.items.first()
    ) + sum(
        float(o.total) * float(o.guest_items.first().ticket_type.event.commission_rate) / 100
        for o in GuestOrder.objects.filter(paid_at__gte=month_start, status='paid').prefetch_related('guest_items__ticket_type__event')
        if o.guest_items.first()
    )

    # Reversements
    withdrawals_count = WithdrawalRequest.objects.filter(created_at__gte=month_start).count()
    withdrawals_volume = WithdrawalRequest.objects.filter(created_at__gte=month_start, status='completed').aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Utilisateurs
    total_users = CustomUser.objects.count()
    organizers = CustomUser.objects.filter(role='organizer').count()

    report = (
        f"=== RAPPORT MENSUEL BCEAO — {now.strftime('%B %Y')} ===\n\n"
        f"TRANSACTIONS :\n"
        f"- Billets vendus : {ticket_orders} (dont {ticket_orders_guest} invité / {ticket_orders_account} avec compte)\n"
        f"- Produits boutique : {store_orders} (dont {store_orders_guest} invité / {store_orders_account} avec compte)\n"
        f"- Total transactions : {ticket_orders + store_orders}\n\n"
        f"VOLUME FINANCIER :\n"
        f"- Billetterie : {int(ticket_volume):,} FCFA\n"
        f"- Boutique : {int(store_volume):,} FCFA\n"
        f"- Volume total : {int(ticket_volume + store_volume):,} FCFA\n"
        f"- Commissions prélevées : {int(ticket_commission):,} FCFA\n\n"
        f"REVERSEMENTS :\n"
        f"- Demandes : {withdrawals_count}\n"
        f"- Montant reversé : {int(withdrawals_volume):,} FCFA\n\n"
        f"UTILISATEURS :\n"
        f"- Total : {total_users}\n"
        f"- Organisateurs : {organizers}\n\n"
        f"Rapport généré automatiquement le {now.strftime('%d/%m/%Y à %H:%M')}"
    )

    # Envoyer aux admins
    admins = CustomUser.objects.filter(role='admin', is_active=True, notify_email=True)
    if admins.exists():
        send_mail(
            subject=f'[IvoirPass] Rapport BCEAO — {now.strftime("%B %Y")}',
            message=report,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=list(admins.values_list('email', flat=True)),
            fail_silently=True,
        )

    return report




# ============================================================
# RAPPORT HEBDOMADAIRE — Envoi automatique chaque lundi 08:30
# ============================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_weekly_report(self):
    """
    Envoie le rapport hebdomadaire (Excel multi-onglets, chiffré en ZIP)
    aux destinataires définis dans WEEKLY_REPORT_RECIPIENTS.

    Planifié par Celery Beat : chaque lundi à 08:30 (Africa/Abidjan).

    Le fichier Excel est protégé par un mot de passe ZIP
    (WEEKLY_REPORT_ZIP_PASSWORD) communiqué hors email aux destinataires.
    """
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from .reports import build_weekly_report_zip

    # ── 1. Destinataires ────────────────────────────────────────────
    recipients_str = getattr(settings, 'WEEKLY_REPORT_RECIPIENTS', '')
    recipients = [e.strip() for e in recipients_str.split(',') if e.strip()]

    if not recipients:
        logger.warning(
            "WEEKLY_REPORT_RECIPIENTS vide dans .env — "
            "rapport hebdomadaire non envoyé."
        )
        return "Aucun destinataire configuré."

    # ── 2. Génération du ZIP chiffré ────────────────────────────────
    try:
        zip_bytes, zip_name, week_range = build_weekly_report_zip()
    except Exception as exc:
        logger.exception("Échec génération du rapport hebdomadaire")
        raise self.retry(exc=exc)

    week_str = (
        f"{week_range[0].strftime('%d/%m/%Y')} → "
        f"{week_range[1].strftime('%d/%m/%Y')}"
    )

    # ── 3. Rendu des templates ──────────────────────────────────────
    context = {
        'week_str':        week_str,
        'platform_name':   'IvoirPass',
        'platform_url':    getattr(settings, 'PAYDUNYA_BASE_URL', 'https://ivoirpass.com'),
        'support_email':   getattr(settings, 'SUPPORT_EMAIL', 'support@ivoirpass.com'),
        'recipients_count': len(recipients),
        'zip_name':        zip_name,
    }

    subject = f"[IvoirPass] Rapport hebdomadaire — {week_str}"

    try:
        html_body = render_to_string('notifications/email/weekly_report.html', context)
        text_body = render_to_string('notifications/email/weekly_report.txt',  context)
    except Exception as exc:
        logger.exception("Templates weekly_report introuvables")
        raise self.retry(exc=exc)

    # ── 4. Construction et envoi de l'email ─────────────────────────
    email = EmailMultiAlternatives(
        subject    = subject,
        body       = text_body,
        from_email = settings.DEFAULT_FROM_EMAIL,
        to         = recipients,
    )
    email.attach_alternative(html_body, 'text/html')
    email.attach(zip_name, zip_bytes, 'application/zip')

    try:
        email.send(fail_silently=False)
        logger.info(
            "Rapport hebdomadaire envoyé à %d destinataire(s) : %s",
            len(recipients), recipients,
        )
        return f"Rapport envoyé — {week_range[0].strftime('%d/%m/%Y')}"
    except Exception as exc:
        logger.exception("Échec envoi du rapport hebdomadaire")
        raise self.retry(exc=exc)