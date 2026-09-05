"""
IvoirPass V2 — Tâches Celery pour les notifications
"""
import logging
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

logger = logging.getLogger(__name__)


def _log_and_report(message, exc=None):
    """
    Journalise une erreur ET la remonte à Sentry (si configuré), pour que
    les échecs attrapés silencieusement (try/except qui ne font que
    logger.error) déclenchent quand même une vraie alerte en production.
    Sans impact si SENTRY_DSN n'est pas défini (Sentry alors inactif).
    """
    logger.error(message)
    try:
        import sentry_sdk
        if exc is not None:
            sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_message(message, level='error')
    except ImportError:
        pass


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


def _log_email_result(action_success, description_success, description_failure, obj, success, error=None):
    """Petit raccourci pour journaliser succès/échec d'envoi d'email dans
    AuditLog, sans jamais faire échouer la tâche Celery appelante."""
    from apps.dashboard.models import AuditLog
    from apps.dashboard.services import log_action
    if success:
        log_action(action=action_success, description=description_success, obj=obj)
    else:
        log_action(
            action=AuditLog.Action.EMAIL_FAILED,
            description=description_failure,
            obj=obj,
            metadata={'error': str(error)[:200]} if error else None,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_email_async(self, order_uuid):
    """
    Envoi des billets par email après paiement — commande utilisateur connecté (Order).
    """
    from apps.dashboard.models import AuditLog
    from apps.tickets.models import Order
    from apps.notifications.service import NotificationService

    try:
        order = Order.objects.get(uuid=order_uuid)
    except Order.DoesNotExist:
        logger.error(f"Commande {order_uuid} introuvable")
        return None

    try:
        NotificationService.ticket_confirmed(order)
        logger.info(f"Billets envoyés pour commande {order.order_number}")
        _log_email_result(
            AuditLog.Action.EMAIL_SENT,
            f"Email de billets envoyé pour la commande {order.order_number}",
            None, order, success=True,
        )
        return f"Tickets sent for {order.order_number}"
    except Exception as exc:
        logger.error(f"Erreur envoi billets {order.order_number}: {exc}")
        _log_email_result(
            None, None,
            f"Échec de l'envoi des billets par email pour la commande {order.order_number}",
            order, success=False, error=exc,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_guest_ticket_email_async(self, guest_order_uuid):
    """
    Envoi des billets par email après paiement — commande invité (GuestOrder).
    """
    from apps.dashboard.models import AuditLog
    from apps.tickets.models import GuestOrder
    from apps.notifications.service import NotificationService

    try:
        order = GuestOrder.objects.get(uuid=guest_order_uuid)
    except GuestOrder.DoesNotExist:
        logger.error(f"Commande invité {guest_order_uuid} introuvable")
        return None

    try:
        NotificationService.guest_tickets_confirmed(order)
        logger.info(f"Billets invité envoyés pour commande {order.order_number}")
        _log_email_result(
            AuditLog.Action.EMAIL_SENT,
            f"Email de billets envoyé pour la commande invité {order.order_number}",
            None, order, success=True,
        )
        return f"Guest tickets sent for {order.order_number}"
    except Exception as exc:
        logger.error(f"Erreur envoi billets invité {order.order_number}: {exc}")
        _log_email_result(
            None, None,
            f"Échec de l'envoi des billets par email pour la commande invité {order.order_number}",
            order, success=False, error=exc,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_download_link_email_async(self, order_uuid):
    """
    Envoi des liens de téléchargement par email.
    """
    from apps.dashboard.models import AuditLog
    from apps.store.models import ProductOrder
    from apps.store.utils import send_download_link_email

    try:
        order = ProductOrder.objects.get(uuid=order_uuid)
    except ProductOrder.DoesNotExist:
        logger.error(f"Commande boutique {order_uuid} introuvable")
        return None

    try:
        send_download_link_email(order)
        logger.info(f"Liens téléchargement envoyés pour {order.order_number}")
        _log_email_result(
            AuditLog.Action.EMAIL_SENT,
            f"Email des liens de téléchargement envoyé pour la commande {order.order_number}",
            None, order, success=True,
        )
        return f"Download links sent for {order.order_number}"
    except Exception as exc:
        logger.error(f"Erreur envoi liens {order.order_number}: {exc}")
        _log_email_result(
            None, None,
            f"Échec de l'envoi des liens de téléchargement pour la commande {order.order_number}",
            order, success=False, error=exc,
        )
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
            try:
                send_mail(
                    subject=f'[IvoirPass Admin] {title}',
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipient_list,
                    fail_silently=False,
                )
                logger.info(f"Notification admin envoyee a {len(recipient_list)} admin(s)")
            except Exception as e:
                _log_and_report(f"Erreur envoi email admin: {e}", exc=e)

    except Exception as exc:
        logger.error(f"Erreur notification admin: {exc}")
        raise self.retry(exc=exc)