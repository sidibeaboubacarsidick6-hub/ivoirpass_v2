"""
IvoirPass V2 — Service SMS
Supporte Orange SMS CI et Twilio en fallback
"""
import requests
import logging
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Clé de cache pour le token OAuth Orange (durée de vie ~1h côté Orange)
ORANGE_TOKEN_CACHE_KEY = 'orange_sms_oauth_token'


class OrangeSMSService:
    """
    Service SMS via Orange CI API.
    Documentation : https://developer.orange.com/apis/sms-ci
    """
    TOKEN_URL = "https://api.orange.com/oauth/v3/token"
    SEND_URL  = "https://api.orange.com/smsmessaging/v1/outbound/{sender}/requests"

    @classmethod
    def _get_token(cls):
        """
        Obtient un token OAuth Orange — avec cache Redis de 55 minutes.

        Orange limite fortement le nombre de tokens par heure. Sans cache,
        chaque SMS ferait 2 appels HTTP (1 OAuth + 1 envoi), ce qui est
        lent et risque un ban côté Orange. Le cache divise ce coût par N.
        """
        cached = cache.get(ORANGE_TOKEN_CACHE_KEY)
        if cached:
            return cached

        import base64
        credentials = base64.b64encode(
            f"{settings.ORANGE_SMS_CLIENT_ID}:"
            f"{settings.ORANGE_SMS_CLIENT_SECRET}".encode()
        ).decode()

        try:
            response = requests.post(
                cls.TOKEN_URL,
                headers={
                    'Authorization': f'Basic {credentials}',
                    'Content-Type':  'application/x-www-form-urlencoded',
                },
                data={'grant_type': 'client_credentials'},
                timeout=15,
            )
            data = response.json()
        except Exception as e:
            logger.error(f"Orange OAuth : erreur réseau : {e}")
            return None

        token = data.get('access_token')
        if token:
            # 55 min (au lieu de 60) pour absorber les dérives d'horloge
            cache.set(ORANGE_TOKEN_CACHE_KEY, token, timeout=55 * 60)
        else:
            logger.error(
                f"Orange OAuth : pas d'access_token dans la réponse. "
                f"status={response.status_code}, body={response.text[:200]}"
            )
        return token

    @classmethod
    def send(cls, phone_number, message):
        """
        Envoie un SMS via Orange CI.

        Args:
            phone_number : numéro au format international (+225XXXXXXXXXX)
            message      : texte du SMS

        Returns:
            bool : True si envoi réussi
        """
        token = cls._get_token()
        if not token:
            logger.error("SMS Orange : impossible d'obtenir un token OAuth")
            return False

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

        # Troncature propre : 157 + "..." = 160 (limite SMS standard)
        if len(message) > 160:
            message = message[:157] + "..."

        try:
            response = requests.post(
                cls.SEND_URL.format(sender=sender_tel),
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type':  'application/json',
                },
                json={
                    "outboundSMSMessageRequest": {
                        "address":       f"tel:{phone_number}",
                        "senderAddress": sender_tel,
                        "senderName":    sender_name,
                        "outboundSMSTextMessage": {
                            "message": message
                        }
                    }
                },
                timeout=15,
            )
            if response.status_code in (200, 201):
                logger.info(f"SMS Orange envoyé à {phone_number}")
                return True
            else:
                logger.error(
                    f"SMS Orange échec {response.status_code}: "
                    f"{response.text[:200]}"
                )
                return False
        except Exception as e:
            logger.error(f"SMS Orange erreur: {e}")
            return False


class TwilioSMSService:
    """Service SMS via Twilio (fallback)."""

    @classmethod
    def send(cls, phone_number, message):
        if len(message) > 160:
            message = message[:157] + "..."
        try:
            from twilio.rest import Client
            client = Client(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN
            )
            client.messages.create(
                body=message,
                from_=settings.TWILIO_FROM_NUMBER,
                to=phone_number
            )
            logger.info(f"SMS Twilio envoyé à {phone_number}")
            return True
        except Exception as e:
            logger.error(f"SMS Twilio erreur: {e}")
            return False


def _normalize_phone(phone_number):
    """
    Normalise un numéro ivoirien vers le format international +225XXXXXXXXXX.

    Gère : espaces, tirets, points, préfixe 00 international, préfixe 225.
    """
    if not phone_number:
        return None

    phone = phone_number.replace(' ', '').replace('-', '').replace('.', '').strip()

    # Préfixe international 00 → +XXX
    if phone.startswith('00'):
        phone = '+' + phone[2:]

    # Déjà au format international
    if phone.startswith('+'):
        return phone

    # Préfixe 225 sans + (ex: 2250700000000)
    if phone.startswith('225'):
        return f"+{phone}"

    # Numéro local CI sans préfixe (ex: 0700000000)
    return f"+225{phone}"


def send_sms(phone_number, message):
    """
    Fonction principale d'envoi SMS.
    Essaie Orange CI en premier, puis Twilio en fallback.

    Args:
        phone_number : numéro international (+225XXXXXXXXXX) ou local
        message      : texte du SMS

    Returns:
        bool : True si au moins un service a réussi (ou si SMS désactivé)
    """
    if not settings.SMS_ENABLED:
        logger.info(f"[SMS DÉSACTIVÉ] À {phone_number}: {message}")
        return True

    if not phone_number:
        logger.warning("send_sms: numéro manquant")
        return False

    phone = _normalize_phone(phone_number)
    if not phone:
        logger.warning(f"send_sms: numéro invalide '{phone_number}'")
        return False

    # Essaie Orange CI
    if settings.ORANGE_SMS_CLIENT_ID:
        if OrangeSMSService.send(phone, message):
            return True

    # Fallback Twilio
    if settings.TWILIO_ACCOUNT_SID:
        return TwilioSMSService.send(phone, message)

    logger.warning("Aucun service SMS configuré")
    return False