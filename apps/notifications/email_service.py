"""
IvoirPass V2 — Service Email
Templates HTML pour chaque type de notification
"""
import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_notification_email(
    to_email,
    subject,
    template_name,
    context,
    attachments=None
):
    """
    Envoie un email HTML avec template.

    Args:
        to_email      : adresse destinataire
        subject       : sujet de l'email
        template_name : nom du template dans notifications/email/
        context       : variables du template
        attachments   : liste de (filename, content, mimetype)
    """
    try:
        # Ajoute les variables globales au contexte
        context.update({
            'platform_name': 'IvoirPass',
            'platform_url':  settings.PAYDUNYA_BASE_URL,
            'year':          timezone.now().year,
            'support_email': settings.IVOIRPASS['CONTACT_EMAIL'],
        })

        # Rendu HTML
        html_content  = render_to_string(
            f'notifications/email/{template_name}.html',
            context
        )
        text_content  = render_to_string(
            f'notifications/email/{template_name}.txt',
            context
        )

        # Construit l'email
        email = EmailMultiAlternatives(
            subject     = f"[IvoirPass] {subject}",
            body        = text_content,
            from_email  = settings.DEFAULT_FROM_EMAIL,
            to          = [to_email],
        )
        email.attach_alternative(html_content, "text/html")

        # Pièces jointes
        if attachments:
            for filename, content, mimetype in attachments:
                email.attach(filename, content, mimetype)

        email.send(fail_silently=False)
        logger.info(f"Email envoyé à {to_email} — {subject}")
        return True

    except Exception as e:
        logger.error(f"Erreur email à {to_email}: {e}")
        return False