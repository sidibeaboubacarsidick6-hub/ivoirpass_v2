"""
IvoirPass V2 — Service SMS
Supporte Orange SMS CI et Twilio en fallback
"""
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class OrangeSMSService:
    """
    Service SMS via Orange CI API.
    Documentation : https://developer.orange.com/apis/sms-ci
    """
    TOKEN_URL  = "https://api.orange.com/oauth/v3/token"
    SEND_URL   = "https://api.orange.com/smsmessaging/v1/outbound/{sender}/requests"

    @classmethod
    def _get_token(cls):
        """Obtient un token OAuth Orange."""
        import base64
        credentials = base64.b64encode(
            f"{settings.ORANGE_SMS_CLIENT_ID}:"
            f"{settings.ORANGE_SMS_CLIENT_SECRET}".encode()
        ).decode()

        response = requests.post(
            cls.TOKEN_URL,
            headers={
                'Authorization': f'Basic {credentials}',
                'Content-Type':  'application/x-www-form-urlencoded',
            },
            data={'grant_type': 'client_credentials'},
            timeout=15
        )
        data = response.json()
        return data.get('access_token')

    @classmethod
    def send(cls, phone_number, message):
        """
        Envoie un SMS via Orange CI.

        Args:
            phone_number : numéro au format international (+225XXXXXXXXXX)
            message      : texte du SMS (max 160 caractères)

        Returns:
            bool : True si envoi réussi
        """
        try:
            token = cls._get_token()
            # senderAddress DOIT être un numéro de téléphone (celui assigné à
            # ton compte développeur Orange, visible sur ton tableau de bord
            # developer.orange.com dans les détails de ton abonnement SMS API)
            # — PAS le nom de la marque. Orange exige que ce numéro soit
            # STRICTEMENT identique dans l'URL et dans le corps de la requête,
            # sinon il rejette avec l'erreur SVC0004.
            # senderName (optionnel) porte le nom affiché ("IvoirPass").
            sender_address = settings.ORANGE_SMS_SENDER_ADDRESS
            sender_name    = settings.ORANGE_SMS_SENDER_NAME

            if not sender_address:
                logger.error(
                    "ORANGE_SMS_SENDER_ADDRESS non configuré — Orange exige un "
                    "numéro de téléphone expéditeur (pas juste un nom de marque). "
                    "Vérifie ce numéro sur https://developer.orange.com dans les "
                    "détails de ton abonnement SMS API CI."
                )
                return False

            sender_tel = f"tel:{sender_address}"

            response = requests.post(
                cls.SEND_URL.format(sender=sender_tel),
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type':  'application/json',
                },
                json={
                    "outboundSMSMessageRequest": {
                        "address":               f"tel:{phone_number}",
                        "senderAddress":         sender_tel,
                        "senderName":            sender_name,
                        "outboundSMSTextMessage": {
                            "message": message[:160]
                        }
                    }
                },
                timeout=15
            )
            if response.status_code in [200, 201]:
                logger.info(f"SMS Orange envoyé à {phone_number}")
                return True
            else:
                logger.error(
                    f"SMS Orange échec {response.status_code}: "
                    f"{response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"SMS Orange erreur: {e}")
            return False


class TwilioSMSService:
    """Service SMS via Twilio (fallback)."""

    @classmethod
    def send(cls, phone_number, message):
        try:
            from twilio.rest import Client
            client = Client(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN
            )
            client.messages.create(
                body=message[:160],
                from_=settings.TWILIO_FROM_NUMBER,
                to=phone_number
            )
            logger.info(f"SMS Twilio envoyé à {phone_number}")
            return True
        except Exception as e:
            logger.error(f"SMS Twilio erreur: {e}")
            return False


def send_sms(phone_number, message):
    """
    Fonction principale d'envoi SMS.
    Essaie Orange CI en premier, puis Twilio en fallback.

    Args:
        phone_number : numéro international (+225XXXXXXXXXX)
        message      : texte du SMS

    Returns:
        bool : True si au moins un service a réussi
    """
    if not settings.SMS_ENABLED:
        logger.info(f"[SMS DÉSACTIVÉ] À {phone_number}: {message}")
        return True

    if not phone_number:
        logger.warning("send_sms: numéro manquant")
        return False

    # Normalise le numéro
    phone = phone_number.replace(' ', '').replace('-', '')
    if not phone.startswith('+'):
        phone = f"+225{phone}"

    # Essaie Orange CI
    if settings.ORANGE_SMS_CLIENT_ID:
        if OrangeSMSService.send(phone, message):
            return True

    # Fallback Twilio
    if settings.TWILIO_ACCOUNT_SID:
        return TwilioSMSService.send(phone, message)

    logger.warning("Aucun service SMS configuré")
    return False