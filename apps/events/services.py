"""
IvoirPass V2 — Services de l'app events.

Contient les opérations métier liées aux événements :
  - cancel_event_organizer_liable : annulation d'un événement
    (l'organisateur est seul responsable du remboursement).

Note (2026-09-27) : l'ancien service `cancel_event_and_refund`
(gestion du remboursement automatique par IvoirPass) a été retiré
après le chantier A — décision métier : IvoirPass n'est pas
responsable du remboursement en cas d'annulation.
"""
from django.db import transaction
from django.utils import timezone


# ============================================================
# CHANTIER A — Annulation événement (organisateur seul responsable)
# ============================================================
# Logique métier décidée le 2026-09-27 :
# - IvoirPass n'est PAS responsable du remboursement
# - L'organisateur gère les remboursements directement
# - Le wallet de l'organisateur est GELÉ s'il y a eu des ventes
# - Les billets deviennent `void` → le scanner les refuse
# - Les commandes passent en CANCELLED (pas REFUNDED)
# ============================================================

@transaction.atomic
def cancel_event_organizer_liable(event, reason="Événement annulé par l'organisateur"):
    """
    Annule un événement avec la nouvelle logique métier :
    l'organisateur est seul responsable du remboursement.

    Effets :
      - event.status = CANCELLED
      - Tous les GuestTicket / Ticket VALID → VOID
      - Tous les GuestOrder / Order PAID → CANCELLED
      - Si au moins 1 commande PAID existait : wallet gelé
        (is_frozen=True + frozen_reason) — aucune demande de
        reversement ne sera acceptée tant qu'un admin n'a pas dégelé
      - Email + SMS informatifs envoyés à chaque acheteur (si
        numéro de téléphone disponible)
      - Email d'alerte envoyé à tous les admins

    Args:
        event: l'Event à annuler.
        reason: texte libre tracé dans frozen_reason et les logs.

    Returns:
        dict {
            'orders_affected': int,   # GuestOrder + Order passés CANCELLED
            'tickets_voided': int,    # GuestTicket + Ticket passés VOID
            'wallet_frozen': bool,    # True si le wallet a été gelé
            'cancelled_at': datetime,
        }
    """
    from apps.dashboard.models import OrganizerWallet
    from apps.notifications.service import NotificationService
    from apps.tickets.models import (
        Order, Ticket,
        GuestOrder, GuestTicket,
    )

    event.status = event.Status.CANCELLED
    event.save(update_fields=['status'])

    # ── 1. Guest tickets + Guest orders ────────────────────────────
    guest_tickets = GuestTicket.objects.filter(
        order_item__ticket_type__event=event,
        status=GuestTicket.Status.VALID,
    ).select_related('order_item__order')

    guest_orders_seen = set()
    tickets_voided = 0
    orders_affected = 0
    # [(email, buyer_name, buyer_phone)] — pour envoi groupé (email + SMS)
    buyer_emails = []

    for ticket in guest_tickets:
        ticket.status = GuestTicket.Status.VOID
        ticket.save(update_fields=['status'])
        tickets_voided += 1

        order = ticket.order_item.order
        if order.id in guest_orders_seen:
            continue
        guest_orders_seen.add(order.id)

        if order.status == GuestOrder.Status.PAID:
            order.status = GuestOrder.Status.CANCELLED
            order.save(update_fields=['status', 'updated_at'])
            orders_affected += 1

        buyer_emails.append(
            (order.email, order.buyer_name, order.phone or None)
        )

    # ── 2. Tickets + Orders "avec compte" (legacy, mais on traite) ──
    account_tickets = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        status=Ticket.Status.VALID,
    ).select_related('order_item__order__buyer')

    account_orders_seen = set()
    for ticket in account_tickets:
        ticket.status = Ticket.Status.VOID
        ticket.save(update_fields=['status'])
        tickets_voided += 1

        order = ticket.order_item.order
        if order.id in account_orders_seen:
            continue
        account_orders_seen.add(order.id)

        if order.status == Order.Status.PAID:
            order.status = Order.Status.CANCELLED
            order.save(update_fields=['status'])
            orders_affected += 1

        if order.buyer and order.buyer.email:
            buyer_emails.append(
                (
                    order.buyer.email,
                    order.buyer.get_full_name(),
                    getattr(order.buyer, 'phone_number', None) or None,
                )
            )

    # ── 3. Gel du wallet si au moins 1 commande PAID a existé ───────
    # On gèle même si le wallet est déjà négatif (décision A14).
    wallet_frozen = False
    if orders_affected > 0:
        wallet, _ = OrganizerWallet.objects.select_for_update().get_or_create(
            organizer=event.organizer
        )
        wallet.is_frozen = True
        wallet.frozen_reason = (
            f"Annulation de l'événement « {event.title} » "
            f"(id={event.id}) — {orders_affected} commande(s) impactée(s). "
            f"Motif : {reason}"
        )
        wallet.save(update_fields=['is_frozen', 'frozen_reason'])
        wallet_frozen = True

    # ── 4. Emails + SMS acheteurs ──────────────────────────────────
    # Best-effort : un échec sur un envoi ne doit pas bloquer les autres.
    import logging
    _logger = logging.getLogger(__name__)

    for email, buyer_name, buyer_phone in buyer_emails:
        if not email:
            continue
        try:
            NotificationService.event_cancelled_buyer(
                buyer_email=email,
                buyer_name=buyer_name,
                event=event,
                buyer_phone=buyer_phone,
            )
        except Exception:
            _logger.exception(
                f"[cancel_event] Échec notification acheteur {email} — event {event.id}"
            )

    # ── 5. Alerte admins ───────────────────────────────────────────
    try:
        NotificationService.event_cancelled_admin_alert(
            event=event,
            orders_affected=orders_affected,
            tickets_voided=tickets_voided,
            wallet_frozen=wallet_frozen,
            reason=reason,
        )
    except Exception:
        _logger.exception(
            f"[cancel_event] Échec alerte admin — event {event.id}"
        )

    return {
        'orders_affected': orders_affected,
        'tickets_voided': tickets_voided,
        'wallet_frozen': wallet_frozen,
        'cancelled_at': timezone.now(),
    }