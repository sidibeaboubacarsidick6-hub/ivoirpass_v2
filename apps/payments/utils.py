"""
IvoirPass V2 — Utilitaires pour le module payments.

Centralise les opérations transverses qui doivent être cohérentes
entre les différents points d'entrée (signaux, tâches Celery, vues).
"""
import logging

logger = logging.getLogger(__name__)


def cancel_pending_payments_for_order(order):
    """
    Annule tous les Payment au statut PENDING associés à une commande.

    Détecte automatiquement le bon FK selon le type de commande
    (order / guest_order / product_order / guest_product_order).

    Idempotent : ne touche que les Payment PENDING, ignore les autres.

    Returns:
        int : nombre de Payment annulés.
    """
    from apps.payments.models import Payment

    # Détecter le bon FK par attribut (pas par isinstance pour rester
    # tolérant aux proxies / sous-classes)
    if hasattr(order, 'guest_items'):
        filters = {'guest_order': order}
    elif hasattr(order, 'items') and not hasattr(order, 'product'):
        filters = {'order': order}
    elif hasattr(order, 'guest_product_items'):
        filters = {'guest_product_order': order}
    elif hasattr(order, 'product') and hasattr(order, 'quantity'):
        filters = {'product_order': order}
    else:
        logger.warning(
            "cancel_pending_payments_for_order : type de commande inconnu %s",
            type(order).__name__,
        )
        return 0

    count = Payment.objects.filter(
        status=Payment.Status.PENDING,
        **filters,
    ).update(status=Payment.Status.CANCELLED)

    if count:
        logger.info(
            "Payment PENDING annulés pour %s (%s) : %d",
            getattr(order, 'order_number', '?'),
            type(order).__name__,
            count,
        )
    return count
