"""
IvoirPass V2 — Tâches Celery pour les notifications
"""
import logging
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_async(self, subject, html_body, text_body, recipient_list,
                     from_email=None, reply_to=None):
    """
    Envoi d'email asynchrone avec retry automatique.
    """
    try:
        from_email = from_email or settings.DEFAULT_FROM_EMAIL
        
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=recipient_list,
            reply_to=reply_to or [from_email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
        
        logger.info(f"Email envoyé à {recipient_list}: {subject}")
        return f"Email sent to {recipient_list}"
        
    except Exception as exc:
        logger.error(f"Échec envoi email à {recipient_list}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_email_async(self, order_uuid):
    """
    Envoi des billets par email après paiement.
    """
    from apps.tickets.models import Order
    from apps.tickets.utils import send_ticket_email
    
    try:
        order = Order.objects.get(uuid=order_uuid)
        send_ticket_email(order)
        logger.info(f"Billets envoyés pour commande {order.order_number}")
        return f"Tickets sent for {order.order_number}"
        
    except Order.DoesNotExist:
        logger.error(f"Commande {order_uuid} introuvable")
        return None
    except Exception as exc:
        logger.error(f"Erreur envoi billets {order_uuid}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_download_link_email_async(self, order_uuid):
    """
    Envoi des liens de téléchargement par email.
    """
    from apps.store.models import ProductOrder
    from apps.store.utils import send_download_link_email
    
    try:
        order = ProductOrder.objects.get(uuid=order_uuid)
        send_download_link_email(order)
        logger.info(f"Liens téléchargement envoyés pour {order.order_number}")
        return f"Download links sent for {order.order_number}"
        
    except ProductOrder.DoesNotExist:
        logger.error(f"Commande boutique {order_uuid} introuvable")
        return None
    except Exception as exc:
        logger.error(f"Erreur envoi liens {order_uuid}: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_qr_codes_async(self, ticket_uuids):
    """
    Génération asynchrone des QR codes après paiement.
    """
    from apps.tickets.models import Ticket
    from apps.tickets.utils import generate_qr_image
    
    try:
        tickets = Ticket.objects.filter(uuid__in=ticket_uuids)
        for ticket in tickets:
            if not ticket.qr_code_image:
                generate_qr_image(ticket)
        logger.info(f"QR codes générés pour {len(tickets)} tickets")
        return f"QR codes generated for {len(tickets)} tickets"
        
    except Exception as exc:
        logger.error(f"Erreur génération QR codes: {exc}")
        raise self.retry(exc=exc)
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def notify_admins_async(self, notification_type, title, message, reference=''):
    """
    Notifie tous les administrateurs par email.
    """
    from apps.accounts.models import CustomUser
    from apps.notifications.models import AdminNotification
    from django.core.mail import send_mail
    from django.conf import settings

    try:
        # Créer la notification en base
        AdminNotification.objects.create(
            type=notification_type,
            title=title,
            message=message,
            reference=reference,
        )

        # Envoyer l'email à tous les admins
        admins = CustomUser.objects.filter(
            role=CustomUser.Role.ADMIN,
            is_active=True,
            notify_email=True,
        )

        if admins.exists():
            recipient_list = list(admins.values_list('email', flat=True))
            send_mail(
                subject=f'[IvoirPass Admin] {title}',
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipient_list,
                fail_silently=True,
            )
            logger.info(f"Notification admin envoyée à {len(recipient_list)} admin(s)")

        return f"Admins notified: {title}"

    except Exception as exc:
        logger.error(f"Erreur notification admin: {exc}")
        raise self.retry(exc=exc)
