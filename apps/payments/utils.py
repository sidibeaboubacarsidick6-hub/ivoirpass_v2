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

    # Détection fiable par isinstance() — les modèles ont des attributs
    # communs (product, quantity...) qui rendent hasattr() ambigu.
    # Imports locaux pour éviter tout import circulaire au chargement.
    from apps.tickets.models import Order, GuestOrder
    from apps.store.models import ProductOrder, GuestProductOrder

    if isinstance(order, Order):
        filters = {'order': order}
    elif isinstance(order, GuestOrder):
        filters = {'guest_order': order}
    elif isinstance(order, ProductOrder):
        filters = {'product_order': order}
    elif isinstance(order, GuestProductOrder):
        filters = {'guest_product_order': order}
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
