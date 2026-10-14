"""
IvoirPass V2 — Signaux de l'app tickets.

Gère automatiquement la restitution du stock lorsqu'une commande
passe de PENDING à CANCELLED (annulation manuelle, admin, webhook,
utilisateur…).

Sans ce signal, une commande annulée laissait `tickets_sold` et
`quantity_sold` figés à leur valeur de réservation initiale — ce qui
faisait apparaître des événements "sold out" alors qu'aucun billet
n'avait été émis.

⚠️ Ne s'applique QU'À la transition PENDING → CANCELLED.
Une commande PAID → CANCELLED (annulation d'événement) ne doit PAS
être traitée ici : les billets ont déjà été émis, le stock est
légitimement consommé.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import GuestOrder, Order

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capture du statut AVANT modification (pre_save)
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=GuestOrder, dispatch_uid='tickets_pre_save_guest_order')
def _capture_guest_order_old_status(sender, instance, **kwargs):
    """Mémorise le statut actuel pour le comparer après le save."""
    if instance.pk is None:
        instance._old_status = None
        return
    try:
        instance._old_status = (
            GuestOrder.objects.filter(pk=instance.pk)
            .values_list('status', flat=True)
            .first()
        )
    except Exception:
        instance._old_status = None


@receiver(pre_save, sender=Order, dispatch_uid='tickets_pre_save_order')
def _capture_order_old_status(sender, instance, **kwargs):
    """Idem pour les commandes avec compte (legacy)."""
    if instance.pk is None:
        instance._old_status = None
        return
    try:
        instance._old_status = (
            Order.objects.filter(pk=instance.pk)
            .values_list('status', flat=True)
            .first()
        )
    except Exception:
        instance._old_status = None


# ---------------------------------------------------------------------------
# Restitution du stock APRÈS save (post_save)
# ---------------------------------------------------------------------------
def _release_stock(order, items_related_name):
    """
    Décrémente quantity_sold et tickets_sold pour les items de la
    commande. Verrouille les TicketType + Event le temps de l'opération.

    Idempotent : si la commande n'est pas PENDING dans la base au
    moment du SELECT FOR UPDATE, on ne fait rien.
    """
    from apps.events.models import TicketType

    items = list(
        getattr(order, items_related_name)
        .select_related('ticket_type', 'ticket_type__event')
    )
    if not items:
        return

    with transaction.atomic():
        # Verrou pessimiste : si un autre appel a déjà traité, on sort.
        locked = type(order).objects.select_for_update().get(pk=order.pk)
        # Si entre-temps quelqu'un a re-modifié le statut, on respecte son choix
        if locked.status != type(order).Status.CANCELLED:
            return

        ticket_type_ids = {item.ticket_type_id for item in items}
        locked_types = {
            tt.pk: tt for tt in
            TicketType.objects.select_for_update()
            .select_related('event')
            .filter(pk__in=ticket_type_ids)
        }

        for item in items:
            tt = locked_types.get(item.ticket_type_id)
            if not tt:
                continue
            tt.quantity_sold = max(0, tt.quantity_sold - item.quantity)
            tt.event.tickets_sold = max(0, tt.event.tickets_sold - item.quantity)
            tt.save(update_fields=['quantity_sold'])
            tt.event.save(update_fields=['tickets_sold'])

    # Annuler les Payment PENDING associés (bug 2026-10-14)
    from apps.payments.utils import cancel_pending_payments_for_order
    cancel_pending_payments_for_order(order)

    logger.info(
        "Stock restitué pour la commande %s (%d item(s))",
        order.order_number, len(items),
    )


@receiver(post_save, sender=GuestOrder, dispatch_uid='tickets_post_save_guest_order')
def _release_stock_on_guest_order_cancel(sender, instance, created, **kwargs):
    """Restitue le stock si GuestOrder passe de PENDING à CANCELLED."""
    if created:
        return

    old_status = getattr(instance, '_old_status', None)

    # On agit UNIQUEMENT sur la transition PENDING → CANCELLED
    if old_status != GuestOrder.Status.PENDING:
        return
    if instance.status != GuestOrder.Status.CANCELLED:
        return

    try:
        _release_stock(instance, 'guest_items')
    except Exception:
        logger.exception(
            "Échec restitution stock pour GuestOrder %s",
            instance.order_number,
        )


@receiver(post_save, sender=Order, dispatch_uid='tickets_post_save_order')
def _release_stock_on_order_cancel(sender, instance, created, **kwargs):
    """Idem pour Order (legacy)."""
    if created:
        return

    old_status = getattr(instance, '_old_status', None)

    if old_status != Order.Status.PENDING:
        return
    if instance.status != Order.Status.CANCELLED:
        return

    try:
        _release_stock(instance, 'items')
    except Exception:
        logger.exception(
            "Échec restitution stock pour Order %s",
            instance.order_number,
        )
