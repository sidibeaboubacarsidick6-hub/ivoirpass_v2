"""
IvoirPass V2 — Signals pour invalidation du cache
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import Event


@receiver(post_save, sender=Event)
@receiver(post_delete, sender=Event)
def invalidate_event_cache(sender, instance, **kwargs):
    """Invalide le cache des événements quand un événement est modifié."""
    # Supprime toutes les clés de cache liées aux événements
    cache.delete_pattern('home_*')
    cache.delete_pattern('event_list_*')
