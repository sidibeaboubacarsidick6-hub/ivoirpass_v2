"""
IvoirPass V2 — Réconciliation PayDunya ↔ IvoirPass (voir audit technique, R-04).

Deux dangers à couvrir sans dépendre uniquement d'un webhook qui pourrait ne
jamais arriver (panne réseau, serveur IvoirPass indisponible au moment de
l'appel PayDunya, etc.) :

1. PayDunya a confirmé le paiement mais IvoirPass ne l'a jamais su → la
   commande reste PENDING indéfiniment alors que l'acheteur a réellement payé
   (préjudice acheteur : payé sans billet).
2. Un paiement reste PENDING très longtemps sans confirmation, ni côté
   PayDunya ni côté IvoirPass → probable abandon, mais à signaler pour
   vérification plutôt qu'ignoré silencieusement.

Cette tâche est volontairement lecture-seule côté PayDunya (elle interroge
uniquement l'API de vérification, elle ne déclenche ni ne modifie rien chez
PayDunya) et ne confirme une commande que via order.mark_as_paid(), qui est
verrouillé et idempotent (voir apps/tickets/models.py — correctif R-01).

Portée actuelle : commandes de billetterie (Order / GuestOrder), qui sont les
seules à disposer d'un enregistrement Payment dédié aujourd'hui. Les commandes
boutique (ProductOrder / GuestProductOrder) ne créent pas de ligne Payment et
ne sont donc pas couvertes par cette tâche — c'est un point distinct à traiter
séparément si la réconciliation doit être étendue à la boutique.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# En dessous de ce délai, on laisse le temps au retour navigateur / webhook
# normal de confirmer — inutile d'interroger PayDunya trop tôt.
RECONCILE_MIN_AGE_MINUTES = 15

# Au-delà de ce délai, un paiement PENDING est considéré comme une anomalie
# à signaler aux admins plutôt que ré-essayé indéfiniment à chaque exécution.
RECONCILE_ANOMALY_AGE_HOURS = 48


@shared_task(bind=True)
def reconcile_pending_payments(self):
    """
    Tâche périodique : pour chaque Payment encore PENDING depuis plus de
    RECONCILE_MIN_AGE_MINUTES, interroge PayDunya pour savoir si le paiement
    a réellement été confirmé côté opérateur, et rattrape la commande si oui.
    """
    from apps.payments.models import Payment
    from apps.payments.paydunya import PayDunyaService

    now = timezone.now()
    min_age = now - timedelta(minutes=RECONCILE_MIN_AGE_MINUTES)
    anomaly_age = now - timedelta(hours=RECONCILE_ANOMALY_AGE_HOURS)

    candidates = Payment.objects.filter(
        status=Payment.Status.PENDING,
        created_at__lte=min_age,
    ).select_related('order', 'guest_order')

    checked = recovered = marked_failed = anomalies = 0

    for payment in candidates:
        token = payment.paydunya_token

        if not token:
            if payment.created_at <= anomaly_age:
                _flag_anomaly(payment, "Paiement PENDING sans token PayDunya depuis plus de "
                                        f"{RECONCILE_ANOMALY_AGE_HOURS}h")
                anomalies += 1
            continue

        checked += 1
        try:
            result = PayDunyaService.verify_payment(token)
        except Exception as e:
            logger.warning(f"Réconciliation: erreur de vérification pour le token {token}: {e}")
            continue

        status = result.get('status', '') or result.get('data', {}).get('invoice', {}).get('status', '')

        if status == 'completed':
            recovered_now = _recover_confirmed_payment(payment, token, result, now)
            if recovered_now:
                recovered += 1
            continue

        if status in ('cancelled', 'failed'):
            Payment.objects.filter(pk=payment.pk, status=Payment.Status.PENDING).update(
                status=Payment.Status.FAILED if status == 'failed' else Payment.Status.CANCELLED,
                raw_response=result,
            )
            marked_failed += 1
            continue

        # Toujours en attente côté PayDunya aussi — anomalie seulement si ça
        # traîne depuis trop longtemps.
        if payment.created_at <= anomaly_age:
            _flag_anomaly(
                payment,
                f"Paiement PENDING depuis plus de {RECONCILE_ANOMALY_AGE_HOURS}h "
                f"(statut PayDunya: {status or 'inconnu'})",
            )
            anomalies += 1

    summary = (
        f"Réconciliation PayDunya: {checked} paiement(s) interrogé(s), "
        f"{recovered} récupéré(s) (webhook manquant), "
        f"{marked_failed} marqué(s) échoué/annulé, "
        f"{anomalies} anomalie(s) signalée(s) aux admins."
    )
    logger.info(summary)
    return summary


def _recover_confirmed_payment(payment, token, result, now):
    """
    PayDunya indique le paiement comme confirmé : rattrape la commande via
    le même mécanisme verrouillé/idempotent que le webhook normal.
    Retourne True si la commande a effectivement été confirmée par cet appel.
    """
    from apps.payments.models import Payment
    from apps.dashboard.models import AuditLog
    from apps.dashboard.services import log_action

    order = payment.order or payment.guest_order
    if order is None:
        _flag_anomaly(payment, "Paiement confirmé chez PayDunya mais sans commande associée en base")
        return False

    newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference=token)

    Payment.objects.filter(pk=payment.pk).update(
        status=Payment.Status.COMPLETED,
        raw_response=result,
        completed_at=now,
    )

    if not newly_confirmed:
        # Déjà confirmée entre-temps par un autre chemin (retour/webhook) —
        # rien de plus à faire, ce n'est pas un webhook manquant.
        return False

    log_action(
        action=AuditLog.Action.RECONCILIATION_RECOVERED,
        description=(
            f"Commande {order.order_number} récupérée par réconciliation : "
            f"PayDunya la déclarait payée, IvoirPass ne l'avait jamais reçu "
            f"(webhook manquant)."
        ),
        model_name=order.__class__.__name__, object_id=order.order_number,
        metadata={'paydunya_token': token, 'amount': str(payment.amount)},
    )
    _dispatch_post_confirmation(order)
    return True


def _flag_anomaly(payment, reason):
    from apps.dashboard.models import AuditLog
    from apps.dashboard.services import log_action

    order = payment.order or payment.guest_order
    log_action(
        action=AuditLog.Action.RECONCILIATION_ANOMALY,
        description=f"Anomalie de réconciliation PayDunya — {reason}",
        model_name='Payment', object_id=str(payment.pk),
        metadata={
            'order_number': getattr(order, 'order_number', ''),
            'amount': str(payment.amount),
            'paydunya_token': payment.paydunya_token,
            'created_at': payment.created_at.isoformat(),
        },
    )
    logger.warning(f"Réconciliation — anomalie signalée: {reason} (Payment #{payment.pk})")


def _dispatch_post_confirmation(order):
    """Envoie l'email des billets pour une commande récupérée par réconciliation."""
    try:
        from apps.tickets.models import Order, GuestOrder
        if isinstance(order, Order):
            from apps.notifications.tasks import send_ticket_email_async
            send_ticket_email_async.delay(str(order.uuid))
        elif isinstance(order, GuestOrder):
            from apps.notifications.tasks import send_guest_ticket_email_async
            send_guest_ticket_email_async.delay(str(order.uuid))
    except Exception as e:
        logger.error(f"Réconciliation: erreur envoi email billets pour {order.order_number}: {e}")
