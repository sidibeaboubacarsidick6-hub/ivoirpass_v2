"""
IvoirPass V2 — Service de notifications
"""
import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class NotificationService:
    """Service centralisé pour les notifications email et SMS."""

    @staticmethod
    def send_email(subject, message, recipient_list, html_message=None, from_email=None):
        from django.core.mail import send_mail
        if not from_email:
            from_email = settings.DEFAULT_FROM_EMAIL
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipient_list,
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Email envoyé à {recipient_list}")
            return True
        except Exception as e:
            logger.error(f"Erreur envoi email : {e}")
            return False

    @staticmethod
    def send_ticket_confirmation(order):
        from apps.tickets.models import Ticket
        from apps.tickets.utils import generate_ticket_pdf

        tickets = Ticket.objects.filter(order_item__order=order)
        if not tickets.exists():
            return False

        context = {
            'order': order, 'tickets': tickets, 'user': order.buyer,
            'platform_name': 'IvoirPass', 'platform_url': settings.PAYDUNYA_BASE_URL,
        }
        subject = f"Vos billets IvoirPass — {order.order_number}"

        try:
            html_message  = render_to_string('notifications/email/ticket_confirmed.html', context)
            plain_message = render_to_string('notifications/email/ticket_confirmed.txt', context)
        except Exception as e:
            logger.error(f"Template ticket_confirmed introuvable: {e}")
            return False

        email = EmailMultiAlternatives(
            subject=subject, body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL, to=[order.buyer.email],
        )
        email.attach_alternative(html_message, "text/html")

        for ticket in tickets:
            try:
                pdf_bytes = generate_ticket_pdf(ticket)
                email.attach(f"billet-{ticket.ticket_number}.pdf", pdf_bytes, 'application/pdf')
            except Exception as e:
                logger.error(f"Erreur PDF {ticket.ticket_number}: {e}")

        try:
            email.send()
            logger.info(f"Email tickets envoyé à {order.buyer.email}")
            return True
        except Exception as e:
            logger.error(f"Erreur envoi email tickets : {e}")
            return False

    @classmethod
    def ticket_confirmed(cls, order):
        return cls.send_ticket_confirmation(order)

    @classmethod
    def guest_tickets_confirmed(cls, order):
        from apps.tickets.models import GuestTicket
        from apps.tickets.utils import generate_guest_ticket_pdf

        tickets = GuestTicket.objects.filter(order_item__order=order).select_related('order_item__ticket_type__event')
        if not tickets.exists():
            return False

        base_url = settings.PAYDUNYA_BASE_URL
        attachments = []
        for ticket in tickets:
            try:
                pdf_bytes = generate_guest_ticket_pdf(ticket)
                attachments.append((f"billet-{ticket.ticket_number}.pdf", pdf_bytes, 'application/pdf'))
            except Exception as e:
                logger.error(f"Erreur PDF invité {ticket.ticket_number}: {e}")

        tickets_with_links = [{'ticket': t, 'download_url': f"{base_url}/billets/guest/billet/{t.ticket_number}/pdf/"} for t in tickets]

        subject = f"Vos billets — {order.order_number}"
        context = {
            'order': order, 'tickets': tickets, 'tickets_with_links': tickets_with_links,
            'buyer_name': order.buyer_name, 'platform_name': 'IvoirPass',
            'platform_url': base_url, 'support_email': settings.IVOIRPASS.get('CONTACT_EMAIL', 'infos@mks-soft-technologies.com'),
            'year': timezone.now().year,
        }

        try:
            html_message  = render_to_string('notifications/email/guest_ticket_confirmed.html', context)
            plain_message = render_to_string('notifications/email/guest_ticket_confirmed.txt', context)
        except Exception as e:
            logger.error(f"Template guest_ticket_confirmed introuvable: {e}")
            return False

        email = EmailMultiAlternatives(subject=subject, body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[order.email])
        email.attach_alternative(html_message, "text/html")
        for filename, content, mimetype in attachments:
            email.attach(filename, content, mimetype)

        try:
            email.send()
            return True
        except Exception as e:
            logger.error(f"Erreur envoi email guest : {e}")
            return False

    @classmethod
    def welcome(cls, user):
        context = {'user': user, 'platform_name': 'IvoirPass', 'platform_url': settings.PAYDUNYA_BASE_URL, 'year': timezone.now().year}
        try:
            html_message  = render_to_string('notifications/email/welcome.html', context)
            plain_message = render_to_string('notifications/email/welcome.txt', context)
        except Exception as e:
            return False
        email = EmailMultiAlternatives(subject="Bienvenue sur IvoirPass !", body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def store_order_confirmed(cls, order):
        from apps.store.models import DownloadLink
        base_url = settings.PAYDUNYA_BASE_URL
        year = timezone.now().year

        if order.product.is_digital:
            template_name = 'notifications/email/store_order_digital'
            subject = f"Votre téléchargement — {order.order_number}"
            download_links = DownloadLink.objects.filter(order=order)
            links_with_urls = [{'link': l, 'url': f"{base_url}/boutique/telecharger/{l.token}/"} for l in download_links]
            context = {'order': order, 'links_with_urls': links_with_urls, 'platform_name': 'IvoirPass', 'platform_url': base_url, 'year': year}
        else:
            template_name = 'notifications/email/store_order_physical'
            subject = f"Commande confirmée — {order.order_number}"
            context = {'order': order, 'platform_name': 'IvoirPass', 'platform_url': base_url, 'year': year}

        try:
            html_message  = render_to_string(f'{template_name}.html', context)
            plain_message = render_to_string(f'{template_name}.txt', context)
        except Exception:
            return False

        email = EmailMultiAlternatives(subject=subject, body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[order.buyer.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def guest_store_order_confirmed(cls, order):
        from apps.store.models import GuestDownloadLink
        base_url = settings.PAYDUNYA_BASE_URL
        year = timezone.now().year

        if order.product.is_digital:
            template_name = 'notifications/email/guest_store_digital'
            subject = f"Vos téléchargements — {order.order_number}"
            download_links = GuestDownloadLink.objects.filter(order=order)
            links_with_urls = [{'link': l, 'url': f"{base_url}/boutique/guest/telecharger/{l.token}/"} for l in download_links]
            context = {'order': order, 'links_with_urls': links_with_urls, 'platform_name': 'IvoirPass', 'platform_url': base_url, 'year': year, 'buyer_name': order.buyer_name}
        else:
            template_name = 'notifications/email/guest_store_physical'
            subject = f"Commande confirmée — {order.order_number}"
            context = {'order': order, 'platform_name': 'IvoirPass', 'platform_url': base_url, 'year': year, 'buyer_name': order.buyer_name}

        try:
            html_message  = render_to_string(f'{template_name}.html', context)
            plain_message = render_to_string(f'{template_name}.txt', context)
        except Exception:
            return False

        email = EmailMultiAlternatives(subject=subject, body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[order.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def withdrawal_received(cls, withdrawal_request):
        wallet = withdrawal_request.wallet
        user = wallet.organizer
        context = {'user': user, 'withdrawal_request': withdrawal_request, 'platform_name': 'IvoirPass', 'platform_url': settings.PAYDUNYA_BASE_URL, 'year': timezone.now().year}
        try:
            html_message  = render_to_string('notifications/email/withdrawal_received.html', context)
            plain_message = render_to_string('notifications/email/withdrawal_received.txt', context)
        except Exception:
            return False
        email = EmailMultiAlternatives(subject=f"Demande de reversement reçue — {withdrawal_request.reference}", body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def withdrawal_processed(cls, withdrawal_request):
        wallet = withdrawal_request.wallet
        user = wallet.organizer
        context = {'user': user, 'withdrawal_request': withdrawal_request, 'platform_name': 'IvoirPass', 'platform_url': settings.PAYDUNYA_BASE_URL, 'year': timezone.now().year}
        try:
            html_message  = render_to_string('notifications/email/withdrawal_processed.html', context)
            plain_message = render_to_string('notifications/email/withdrawal_processed.txt', context)
        except Exception:
            return False
        email = EmailMultiAlternatives(subject=f"Reversement effectué — {withdrawal_request.reference}", body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def event_reminder(cls, ticket):
        user = ticket.buyer
        event = ticket.event
        context = {'user': user, 'ticket': ticket, 'event': event, 'platform_name': 'IvoirPass', 'platform_url': settings.PAYDUNYA_BASE_URL, 'year': timezone.now().year}
        try:
            html_message  = render_to_string('notifications/email/event_reminder.html', context)
            plain_message = render_to_string('notifications/email/event_reminder.txt', context)
        except Exception:
            return False
        email = EmailMultiAlternatives(subject=f"Rappel — {event.title} demain !", body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def event_cancelled(cls, ticket):
        user = ticket.buyer
        event = ticket.event
        context = {'user': user, 'ticket': ticket, 'event': event, 'platform_name': 'IvoirPass', 'platform_url': settings.PAYDUNYA_BASE_URL, 'year': timezone.now().year}
        try:
            html_message  = render_to_string('notifications/email/event_cancelled.html', context)
            plain_message = render_to_string('notifications/email/event_cancelled.txt', context)
        except Exception:
            return False
        email = EmailMultiAlternatives(subject=f"Événement annulé — {event.title}", body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            return True
        except Exception:
            return False

    @classmethod
    def send_download_link_email(cls, order):
        return cls.store_order_confirmed(order)

    @classmethod
    def notify_seller_new_order(cls, order, is_guest=False):
        """Notifie le vendeur d'une nouvelle commande physique à livrer."""
        if not order.product.is_physical:
            return False

        seller = order.product.seller
        base_url = settings.PAYDUNYA_BASE_URL

        if is_guest:
            buyer_name  = order.buyer_name
            buyer_email = order.email
            buyer_phone = order.phone
        else:
            buyer_name  = order.buyer.get_full_name()
            buyer_email = order.buyer.email
            buyer_phone = order.buyer.phone_number

        context = {
            'seller': seller, 'order': order,
            'buyer_name': buyer_name, 'buyer_email': buyer_email,
            'buyer_phone': buyer_phone, 'platform_name': 'IvoirPass',
            'platform_url': base_url, 'year': timezone.now().year,
        }

        try:
            html_message  = render_to_string('notifications/email/seller_new_order.html', context)
            plain_message = render_to_string('notifications/email/seller_new_order.txt', context)
        except Exception as e:
            logger.error(f"Template seller_new_order introuvable: {e}")
            return False

        email = EmailMultiAlternatives(
            subject=f"Nouvelle commande a livrer — {order.order_number}",
            body=plain_message, from_email=settings.DEFAULT_FROM_EMAIL, to=[seller.email],
        )
        email.attach_alternative(html_message, "text/html")
        try:
            email.send()
            logger.info(f"Notification vendeur envoyee a {seller.email} pour {order.order_number}")
            return True
        except Exception as e:
            logger.error(f"Erreur notification vendeur : {e}")
            return False
