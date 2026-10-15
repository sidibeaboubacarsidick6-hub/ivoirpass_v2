"""
IvoirPass V2 — Signaux dashboard.

Contient :
1. Crédit wallet unifié (Order, GuestOrder, ProductOrder, GuestProductOrder)
2. Notifications email sur les messages de litige (DisputeMessage)
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.tickets.models import Order, GuestOrder

from .models import DisputeMessage

logger = logging.getLogger(__name__)


# ============================================================
# WALLET — Crédit unifié depuis une commande tickets
# ============================================================

def _credit_from_ticket_order(instance, items_related_name='items'):
    """
    Fonction commune : crédite le wallet organisateur depuis
    une commande de tickets (Order ou GuestOrder), sans jamais
    créditer deux fois la même commande.
    """
    from .models import OrganizerWallet, WalletTransaction

    # ✅ Anti-doublon (garde applicative rapide, non bloquante à elle
    # seule) : vérifie si une transaction existe déjà pour cette commande.
    # La garantie réelle contre un double crédit est la contrainte unique
    # en base sur (wallet, reference) pour type=credit (voir
    # WalletTransaction.Meta.constraints) — cette vérification n'est qu'une
    # optimisation pour éviter un travail inutile dans le cas normal.
    already_credited = WalletTransaction.objects.filter(
        reference=instance.order_number
    ).exists()
    if already_credited:
        return

    earnings = {}
    items = getattr(instance, items_related_name).select_related(
        'ticket_type__event__organizer'
    ).all()

    for item in items:
        event     = item.ticket_type.event
        organizer = event.organizer

        commission_rate = float(event.commission_rate) / 100
        net_amount      = float(item.subtotal) * (1 - commission_rate)

        if organizer.id not in earnings:
            earnings[organizer.id] = {
                'organizer':  organizer,
                'amount':     0,
                'events':     set(),
                'commission': commission_rate,
            }
        earnings[organizer.id]['amount'] += net_amount
        earnings[organizer.id]['events'].add(event.title)

    for org_id, data in earnings.items():
        try:
            # transaction.atomic() + select_for_update() : verrouille la
            # ligne wallet pendant la vérification + l'écriture, pour que
            # deux appels concurrents (post_save déclenché deux fois pour
            # la même commande) ne puissent jamais passer tous les deux la
            # vérification anti-doublon avant que l'un des deux n'ait écrit.
            # La contrainte unique en base (wallet, reference, type=credit)
            # est le filet de sécurité final si ce verrou était contourné.
            with transaction.atomic():
                wallet, _ = OrganizerWallet.objects.get_or_create(
                    organizer=data['organizer']
                )
                wallet = OrganizerWallet.objects.select_for_update().get(pk=wallet.pk)

                if WalletTransaction.objects.filter(
                    wallet=wallet, reference=instance.order_number,
                    type=WalletTransaction.Type.CREDIT,
                ).exists():
                    continue

                events_str = ', '.join(list(data['events'])[:2])
                wallet.credit(
                    amount      = int(round(data['amount'])),
                    source      = 'events',
                    description = f"Vente billetterie — {events_str}",
                    reference   = instance.order_number,
                )
            logger.info(
                f"Wallet crédité (billetterie) : {data['organizer'].email} "
                f"→ {int(round(data['amount']))} FCFA — réf {instance.order_number}"
            )
        except IntegrityError:
            # Filet de sécurité : un appel concurrent a écrit la même
            # transaction juste avant nous malgré le verrou (ex. deux
            # workers Celery/webhook sur des connexions DB séparées).
            logger.warning(
                f"Double crédit wallet évité par la contrainte unique pour "
                f"{data['organizer'].email} — réf {instance.order_number}"
            )
        except Exception as e:
            logger.error(
                f"Erreur crédit wallet billetterie {data['organizer'].email}: {e}"
            )


# ✅ dispatch_uid : empêche un double enregistrement du receiver si le
# module venait à être importé deux fois (imports circulaires, rechargement
# de module en dev). Sans impact fonctionnel — juste une protection.
@receiver(post_save, sender=Order, dispatch_uid='credit_wallet_from_order')
def credit_organizer_wallet_from_order(sender, instance, **kwargs):
    """Crédite le wallet pour les commandes tickets AVEC compte."""
    if instance.status != Order.Status.PAID:
        return
    _credit_from_ticket_order(instance, items_related_name='items')


@receiver(post_save, sender=GuestOrder, dispatch_uid='credit_wallet_from_guest_order')
def credit_organizer_wallet_from_guest_order(sender, instance, **kwargs):
    """
    Crédite le wallet pour les commandes tickets SANS compte.
    ✅ C'était le trou qui causait la perte de revenus.
    """
    if instance.status != GuestOrder.Status.PAID:
        return
    _credit_from_ticket_order(instance, items_related_name='guest_items')


# ============================================================
# LITIGES — Notification email sur nouveau message
# ============================================================

@receiver(post_save, sender=DisputeMessage, dispatch_uid='notify_dispute_message')
def notify_on_dispute_message(sender, instance, created, **kwargs):
    """
    Email automatique à chaque message (ajout 2026-10-15).

    - Client répond (author=None) → email aux admins MKS
    - Agent répond (author=User) → email au client
    Les notes internes (is_internal=True) ne déclenchent rien.
    """
    if not created or instance.is_internal:
        return

    dispute = instance.dispute
    site_url = getattr(settings, 'SITE_URL', 'https://prepod.ivoirpass.com').rstrip('/')

    support_emails = getattr(
        settings, 'DISPUTE_NOTIFICATION_EMAILS',
        ['infos@mks-soft-technologies.com', 'ivoirpass@gmail.com'],
    )

    if instance.author_id:
        # ─── Agent → client ───────────────────────────────────
        if not dispute.email:
            return
        try:
            send_mail(
                subject=f"[{dispute.reference}] Réponse à votre réclamation",
                message=(
                    f"Bonjour,\n\n"
                    f"Vous avez reçu une réponse à votre réclamation "
                    f"{dispute.reference} :\n\n"
                    f"{instance.content}\n\n"
                    f"Pour répondre, suivez ce lien :\n"
                    f"{site_url}/reclamation/{dispute.access_token}/\n\n"
                    f"Cordialement,\n"
                    f"L'équipe IvoirPass"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[dispute.email],
                fail_silently=True,
            )
        except Exception as e:
            logger.warning(
                f"Échec envoi email client litige {dispute.reference}: {e}"
            )
    else:
        # ─── Client → admins ──────────────────────────────────
        try:
            send_mail(
                subject=f"[{dispute.reference}] Nouveau message du client",
                message=(
                    f"Nouveau message sur la réclamation {dispute.reference}.\n\n"
                    f"De : {instance.author_email or dispute.email}\n"
                    f"Type : {dispute.get_type_display()}\n"
                    f"Priorité : {dispute.get_priority_display()}\n\n"
                    f"Message :\n{instance.content}\n\n"
                    f"Traiter : {site_url}/admin/dashboard/dispute/"
                    f"{dispute.pk}/change/"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=support_emails,
                fail_silently=True,
            )
        except Exception as e:
            logger.warning(
                f"Échec envoi email admins litige {dispute.reference}: {e}"
            )