"""
IvoirPass V2 — Tâches Celery pour le dashboard
"""
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings

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
