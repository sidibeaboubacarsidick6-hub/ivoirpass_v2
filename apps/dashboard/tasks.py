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
        status__in=[
            WithdrawalRequest.Status.PENDING,
            WithdrawalRequest.Status.APPROVED,
        ],
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

@shared_task(bind=True)
def generate_bceao_report(self):
    """
    Génère un rapport mensuel pour la BCEAO.
    """
    from django.utils import timezone
    from datetime import timedelta
    from apps.tickets.models import Order
    from apps.store.models import ProductOrder
    from apps.dashboard.models import WithdrawalRequest, OrganizerWallet
    from apps.accounts.models import CustomUser
    from django.core.mail import send_mail
    from django.conf import settings
    import io

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0)

    # Nombre de transactions
    ticket_orders = Order.objects.filter(paid_at__gte=month_start, status='paid').count()
    store_orders = ProductOrder.objects.filter(paid_at__gte=month_start, status='paid').count()

    # Volume financier
    ticket_volume = Order.objects.filter(paid_at__gte=month_start, status='paid').aggregate(
        total=Sum('total')
    )['total'] or 0
    store_volume = ProductOrder.objects.filter(paid_at__gte=month_start, status='paid').aggregate(
        total=Sum('total')
    )['total'] or 0

    # Commissions
    ticket_commission = sum(
        float(o.total) * float(o.items.first().ticket_type.event.commission_rate) / 100
        for o in Order.objects.filter(paid_at__gte=month_start, status='paid').prefetch_related('items__ticket_type__event')
        if o.items.first()
    )

    # Reversements
    withdrawals_count = WithdrawalRequest.objects.filter(created_at__gte=month_start).count()
    withdrawals_volume = WithdrawalRequest.objects.filter(created_at__gte=month_start, status='processed').aggregate(
        total=Sum('amount')
    )['total'] or 0

    # Utilisateurs
    total_users = CustomUser.objects.count()
    organizers = CustomUser.objects.filter(role='organizer').count()

    report = (
        f"=== RAPPORT MENSUEL BCEAO — {now.strftime('%B %Y')} ===\n\n"
        f"TRANSACTIONS :\n"
        f"- Billets vendus : {ticket_orders}\n"
        f"- Produits boutique : {store_orders}\n"
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