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

Portée : commandes de billetterie (Order / GuestOrder) et commandes boutique
invité (GuestProductOrder) — ces dernières ont été ajoutées après coup (voir
audit) via l'extension du modèle Payment. Les commandes boutique "avec
compte" (ProductOrder) restent hors périmètre car ce tunnel d'achat est
désactivé côté site (voir apps/store/views.py).
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
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
    ).select_related('order', 'guest_order', 'product_order', 'guest_product_order')

    checked = recovered = marked_failed = anomalies = 0
    anomaly_details = []

    for payment in candidates:
        token = payment.paydunya_token

        if not token:
            if payment.created_at <= anomaly_age:
                reason = ("Paiement PENDING sans token PayDunya depuis plus de "
                           f"{RECONCILE_ANOMALY_AGE_HOURS}h")
                _flag_anomaly(payment, reason)
                anomaly_details.append(_describe_anomaly(payment, reason))
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
            reason = (f"Paiement PENDING depuis plus de {RECONCILE_ANOMALY_AGE_HOURS}h "
                       f"(statut PayDunya: {status or 'inconnu'})")
            _flag_anomaly(payment, reason)
            anomaly_details.append(_describe_anomaly(payment, reason))
            anomalies += 1

    if anomaly_details:
        _send_anomaly_alert(anomaly_details)

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

    order = payment.order or payment.guest_order or payment.product_order or payment.guest_product_order
    if order is None:
        _flag_anomaly(payment, "Paiement confirmé chez PayDunya mais sans commande associée en base")
        return False

    # ✅ H-2 : mark_as_paid() peut lever ValueError si le stock (boutique
    # physique) est devenu insuffisant entre-temps. Avant ce correctif,
    # cette exception n'était interceptée nulle part dans cette tâche : elle
    # remontait telle quelle, interrompant tout le batch de réconciliation
    # en cours (les autres paiements PENDING du même lot n'étaient alors
    # traités qu'au cycle suivant), et se reproduisait à l'identique toutes
    # les 20 minutes tant que personne n'intervenait manuellement.
    try:
        newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference=token)
    except ValueError as e:
        logger.error(
            f"[H-2] Réconciliation : paiement {token} confirmé chez PayDunya "
            f"pour {order.order_number} mais non confirmable (stock) : {e}"
        )
        log_action(
            action=AuditLog.Action.PAYMENT_PAID_STOCK_UNAVAILABLE,
            description=(
                f"Réconciliation : paiement PayDunya confirmé pour "
                f"{order.order_number}, mais confirmation impossible (stock "
                f"produit insuffisant). Intervention manuelle requise."
            ),
            model_name=order.__class__.__name__, object_id=order.order_number,
            metadata={'paydunya_token': token, 'amount': str(payment.amount), 'error': str(e)[:200]},
        )
        # Réutilise l'alerte email existante (même destinataires, même
        # format) plutôt que d'en dupliquer une nouvelle.
        _send_anomaly_alert([_describe_anomaly(payment, f"Payé mais stock indisponible : {e}")])
        return False

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


def _describe_anomaly(payment, reason):
    order = payment.order or payment.guest_order
    order_number = getattr(order, 'order_number', '—')
    return f"- {order_number} : {payment.amount} {payment.currency} — {reason}"


def _send_anomaly_alert(anomaly_details):
    """
    Alerte les admins par email dès qu'au moins une anomalie de
    réconciliation est détectée — même patron que
    check_pending_withdrawals (apps/dashboard/tasks.py) pour rester cohérent.
    Best-effort : une erreur d'envoi n'interrompt jamais la réconciliation
    elle-même (fail_silently=True), les anomalies restent de toute façon
    tracées dans AuditLog même si l'email échoue.
    """
    from apps.accounts.models import CustomUser

    message = (
        f"⚠️ {len(anomaly_details)} anomalie(s) de réconciliation PayDunya détectée(s) :\n\n"
        + "\n".join(anomaly_details)
        + "\n\nDétail consultable dans le journal d'audit (back-office → Journal d'audit, "
        "action \"Anomalie détectée en réconciliation\") ou dans la fiche de chaque "
        "transaction concernée (back-office → Transactions)."
    )

    admins = CustomUser.objects.filter(
        role=CustomUser.Role.ADMIN, is_active=True, notify_email=True,
    )
    if not admins.exists():
        logger.warning("Réconciliation: anomalies détectées mais aucun admin à notifier (notify_email=False ?)")
        return

    recipient_list = list(admins.values_list('email', flat=True))
    send_mail(
        subject=f"[IvoirPass] ⚠️ {len(anomaly_details)} anomalie(s) de réconciliation PayDunya",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipient_list,
        fail_silently=True,
    )
    logger.info(f"Alerte réconciliation envoyée à {len(recipient_list)} admin(s)")


# ============================================================
# ✅ CORRECTIF AUDIT — H-1 : libération du stock billetterie
# réservé par des commandes abandonnées (jamais payées).
#
# guest_checkout / le tunnel "avec compte" réservent quantity_sold dès la
# CRÉATION de la commande (statut PENDING), avant tout paiement — voir
# apps/tickets/views.py. Si l'acheteur n'initie jamais de paiement (aucun
# Payment associé, ou un Payment resté PENDING sans jamais avoir de token
# PayDunya), ce stock reste bloqué indéfiniment : reconcile_pending_payments
# ne fait qu'alerter les admins après 48h, il ne libère rien.
#
# Cette tâche annule automatiquement ces commandes fantômes et restaure le
# stock, sous le même verrou (select_for_update) que guest_checkout / le
# tunnel "avec compte", pour rester cohérente avec eux en cas de concurrence.
# ============================================================

# Délai de grâce avant de considérer une commande PENDING comme abandonnée.
# Volontairement plus long que RECONCILE_MIN_AGE_MINUTES (15 min) pour ne
# jamais entrer en conflit avec un paiement PayDunya encore en cours côté
# opérateur au moment où cette tâche tourne.
ORDER_ABANDON_GRACE_MINUTES = 30


@shared_task(bind=True)
def release_expired_pending_orders(self):
    """
    Tâche périodique : annule les commandes billetterie (Order / GuestOrder)
    encore PENDING depuis plus de ORDER_ABANDON_GRACE_MINUTES ET sans aucun
    paiement PayDunya initié (pas de Payment, ou Payment sans token — donc
    jamais redirigé vers PayDunya), et restaure le stock correspondant.

    Ne touche JAMAIS une commande dont un Payment a un token PayDunya : ce
    cas est du ressort de reconcile_pending_payments (le paiement peut être
    réellement en cours ou confirmé côté PayDunya).
    """
    from django.db import transaction
    from apps.tickets.models import Order, GuestOrder
    from apps.events.models import TicketType
    from apps.dashboard.models import AuditLog
    from apps.dashboard.services import log_action

    cutoff = timezone.now() - timedelta(minutes=ORDER_ABANDON_GRACE_MINUTES)
    released = 0

    for model in (Order, GuestOrder):
        stale_qs = model.objects.filter(
            status=model.Status.PENDING,
            created_at__lte=cutoff,
        ).exclude(
            payments__paydunya_token__gt=''
        )

        for order in stale_qs:
            released += _release_order_stock(order, AuditLog, log_action)

    summary = f"Libération stock billetterie : {released} commande(s) expirée(s) annulée(s)."
    logger.info(summary)
    return summary


def _release_order_stock(order, AuditLog, log_action):
    """
    Annule une commande PENDING abandonnée et restaure le stock des
    TicketType concernés, verrouillés le temps de l'opération — même
    patron que la réservation initiale (guest_checkout / checkout).
    Retourne 1 si la commande a bien été libérée par cet appel, 0 sinon
    (déjà traitée entre-temps par un appel concurrent).
    """
    from django.db import transaction
    from apps.events.models import TicketType

    items_related_name = 'guest_items' if hasattr(order, 'guest_items') else 'items'
    items = list(getattr(order, items_related_name).select_related('ticket_type', 'ticket_type__event'))
    if not items:
        return 0

    with transaction.atomic():
        locked_order = type(order).objects.select_for_update().get(pk=order.pk)
        if locked_order.status != order.Status.PENDING:
            # Confirmée ou déjà annulée entre-temps par un autre appel —
            # rien à faire, on ne touche pas au stock une deuxième fois.
            return 0

        locked_order.status = order.Status.CANCELLED
        locked_order.save(update_fields=['status'])

        ticket_type_ids = {item.ticket_type_id for item in items}
        locked_types = {
            tt.pk: tt for tt in
            TicketType.objects.select_for_update().select_related('event').filter(pk__in=ticket_type_ids)
        }

        for item in items:
            tt = locked_types[item.ticket_type_id]
            tt.quantity_sold = max(0, tt.quantity_sold - item.quantity)
            tt.event.tickets_sold = max(0, tt.event.tickets_sold - item.quantity)
            tt.save(update_fields=['quantity_sold'])
            tt.event.save(update_fields=['tickets_sold'])

    log_action(
        action=AuditLog.Action.ORDER_STOCK_RELEASED,
        description=(
            f"Commande {order.order_number} annulée automatiquement "
            f"(abandonnée depuis plus de {ORDER_ABANDON_GRACE_MINUTES} min "
            f"sans paiement initié) — stock restauré."
        ),
        model_name=type(order).__name__, object_id=order.order_number,
        metadata={'items_count': len(items)},
    )
    return 1


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
    """Envoie la confirmation (email billets ou email boutique) pour une commande récupérée par réconciliation."""
    try:
        from apps.tickets.models import Order, GuestOrder
        from apps.store.models import GuestProductOrder
        if isinstance(order, Order):
            from apps.notifications.tasks import send_ticket_email_async
            send_ticket_email_async.delay(str(order.uuid))
        elif isinstance(order, GuestOrder):
            from apps.notifications.tasks import send_guest_ticket_email_async
            send_guest_ticket_email_async.delay(str(order.uuid))
        elif isinstance(order, GuestProductOrder):
            from apps.notifications.service import NotificationService
            NotificationService.guest_store_order_confirmed(order)
    except Exception as e:
        logger.error(f"Réconciliation: erreur envoi confirmation pour {order.order_number}: {e}")
