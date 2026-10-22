"""
IvoirPass V2 — Envoi de SMS via la passerelle paas-notifications (Orange).
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SMS_API_URL = "https://paas-notifications.com/sms/orange/send/"


def _format_phone(phone):
    """Retourne '225' + 10 chiffres (ex: 2250709430661), ou '' si invalide."""
    digits = ''.join(c for c in str(phone or '') if c.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('225'):
        digits = digits[3:]
    return f"225{digits}" if len(digits) == 10 else ''


def send_sms(phone_number, message):
    """Envoie un SMS. Retourne True si succès (ou si SMS désactivé), False sinon."""
    if not getattr(settings, 'SMS_ENABLED', False):
        logger.info("[SMS DÉSACTIVÉ] À %s: %s", phone_number, message)
        return True

    to = _format_phone(phone_number)
    if not to:
        logger.warning("SMS: numéro invalide '%s'", phone_number)
        return False
    if not message:
        logger.warning("SMS: message vide")
        return False

    if len(message) > 160:
        message = message[:157] + "..."

    payload = {
        '_to': to,
        'message': message,
        '_from': getattr(settings, 'SMS_SENDER_ID', 'DIGITICKETS'),
        'country': 'ivory-coast',
    }

    try:
        response = requests.post(SMS_API_URL, data=payload, timeout=15)
    except requests.RequestException as e:
        logger.error("SMS: erreur réseau vers %s : %s", to, e)
        return False

    if response.status_code in (200, 201, 202):
        logger.info("SMS envoyé à %s (HTTP %s) : %s",
                    to, response.status_code, response.text[:200])
        return True

    logger.error("SMS: échec HTTP %s pour %s : %s",
                 response.status_code, to, response.text[:200])
    return False