"""
IvoirPass V2 — Signaux pour les notifications
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.events.models import Event
from apps.store.models import Product
from apps.dashboard.models import WithdrawalRequest
from .tasks import notify_admins_async


@receiver(post_save, sender=Event)
def notify_new_event(sender, instance, created, **kwargs):
    """Notifie les admins quand un événement est publié."""
    if created and instance.status == Event.Status.PUBLISHED:
        notify_admins_async.delay(
            notification_type='new_event',
            title=f'Nouvel événement publié',
            message=(
                f"L'organisateur {instance.organizer.get_full_name()} "
                f"a publié l'événement « {instance.title} ».\n"
                f"Date : {instance.start_date.strftime('%d/%m/%Y')}\n"
                f"Lieu : {instance.venue_name}, {instance.venue_city}"
            ),
            reference=instance.slug,
        )
    elif not created and instance.status == Event.Status.PUBLISHED:
        # Événement passé de brouillon à publié
        old_status = instance.tracker.previous('status') if hasattr(instance, 'tracker') else None
        if old_status and old_status != Event.Status.PUBLISHED:
            notify_admins_async.delay(
                notification_type='new_event',
                title=f'Événement publié',
                message=(
                    f"L'événement « {instance.title} » "
                    f"vient d'être publié par {instance.organizer.get_full_name()}."
                ),
                reference=instance.slug,
            )


@receiver(post_save, sender=Product)
def notify_new_product(sender, instance, created, **kwargs):
    """Notifie les admins quand un produit est publié."""
    if instance.status == Product.Status.PUBLISHED:
        is_new = created
        is_just_published = not created and instance.tracker.previous('status') != Product.Status.PUBLISHED if hasattr(instance, 'tracker') else False

        if is_new or is_just_published:
            notify_admins_async.delay(
                notification_type='new_product',
                title=f'Nouveau produit en boutique',
                message=(
                    f"Le vendeur {instance.seller.get_full_name()} "
                    f"a publié le produit « {instance.name} ».\n"
                    f"Prix : {instance.price} FCFA\n"
                    f"Type : {instance.get_product_type_display()}"
                ),
                reference=instance.slug,
            )


@receiver(post_save, sender=WithdrawalRequest)
def notify_withdrawal_request(sender, instance, created, **kwargs):
    """Notifie les admins d'une nouvelle demande de reversement."""
    if created:
        notify_admins_async.delay(
            notification_type='withdrawal',
            title=f'Demande de reversement',
            message=(
                f"L'organisateur {instance.wallet.organizer.get_full_name()} "
                f"demande un reversement de {instance.amount} FCFA.\n"
                f"Référence : {instance.reference}\n"
                f"Méthode : {instance.get_payout_method_display()}\n"
                f"Téléphone : {instance.payout_phone}\n"
                f"Bénéficiaire : {instance.payout_name}"
            ),
            reference=instance.reference,
        )
