from django.db import transaction
from django.utils import timezone

from apps.dashboard.models import OrganizerWallet
from apps.tickets.models import GuestOrder, GuestTicket
from apps.notifications.service import NotificationService


@transaction.atomic
def cancel_event_and_refund(event, reason="Événement annulé par organisateur"):
    """
    Annule un événement et fait supporter à l'organisateur
    le coût intégral des remboursements clients.

    Règle métier :
    - le client récupère 100 % du montant payé ;
    - la commission IvoirPass déjà perçue reste acquise à IvoirPass ;
    - le coût du remboursement est imputé à l'organisateur ;
    - le solde de l'organisateur peut devenir négatif.
    """

    event.status = event.Status.CANCELLED
    event.save(update_fields=["status"])

    wallet = OrganizerWallet.objects.select_for_update().get(
        organizer=event.organizer
    )

    refunded_orders = set()
    total_refunded = 0

    guest_tickets = GuestTicket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=GuestOrder.Status.PAID,
        status=GuestTicket.Status.VALID,
    ).select_related("order_item__order")

    for ticket in guest_tickets:
        order = ticket.order_item.order

        if order.id in refunded_orders:
            continue

        amount = order.total

        order.status = GuestOrder.Status.REFUNDED
        order.save(update_fields=["status", "updated_at"])

        wallet.refund_charge(
            amount,
            description=f"Remboursement client — {event.title}",
            reference=f"EVENT-{event.id}-GUESTORDER-{order.id}",
        )

        NotificationService.event_cancelled(ticket)

        refunded_orders.add(order.id)
        total_refunded += amount

    return {
        "orders_refunded": len(refunded_orders),
        "total_refunded": total_refunded,
        "cancelled_at": timezone.now(),
    }
