"""
IvoirPass V2 — Signaux de notifications
Déclenchement automatique après chaque événement clé
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender='tickets.Order')
def on_order_paid(sender, instance, **kwargs):
    """Envoie les billets par email quand une commande est payée."""
    if instance.status == 'paid':
        # Vérifie qu'on n'a pas déjà envoyé
        if not hasattr(instance, '_notification_sent'):
            instance._notification_sent = True
            try:
                from .service import NotificationService
                NotificationService.ticket_confirmed(instance)
            except Exception as e:
                logger.error(f"Notification tickets erreur: {e}")


@receiver(post_save, sender='store.ProductOrder')
def on_store_order_paid(sender, instance, **kwargs):
    """Notifie après confirmation commande boutique."""
    if instance.status != 'paid':
        return
    if hasattr(instance, '_notification_sent'):
        return
    instance._notification_sent = True

    # Attend que les liens soient générés avant d'envoyer l'email
    from apps.store.models import DownloadLink
    from django.utils import timezone
    import time

    # Petit délai pour s'assurer que les liens sont en base
    max_attempts = 3
    for attempt in range(max_attempts):
        links_count = DownloadLink.objects.filter(order=instance).count()
        if links_count > 0 or not instance.product.is_digital:
            break
        time.sleep(0.5)

    try:
        from .service import NotificationService
        NotificationService.store_order_confirmed(instance)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"Notification store erreur: {e}"
        )


@receiver(post_save, sender='dashboard.WithdrawalRequest')
def on_withdrawal_request(sender, instance, created, **kwargs):
    """Notifie l'organisateur de l'état de son reversement."""
    try:
        from .service import NotificationService
        if created:
            NotificationService.withdrawal_received(instance)
        elif instance.status == 'processed':
            NotificationService.withdrawal_processed(instance)
    except Exception as e:
        logger.error(f"Notification withdrawal erreur: {e}")