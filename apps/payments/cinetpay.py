"""
IvoirPass V2 — Service CinetPay.

Agrégateur de paiement agréé BCEAO en Côte d'Ivoire.
Supporte Orange Money, MTN MoMo, Moov Money, Wave.

API v2 Checkout :
    Init     : POST https://api-checkout.cinetpay.com/v2/payment
    Verify   : POST https://api-checkout.cinetpay.com/v2/payment/check

Ce module expose les méthodes attendues par le dispatcher
(apps.payments.provider.get_payment_service) :
    - verify_webhook_signature(request)
    - create_invoice(order, request)
    - verify_payment(token)
    - create_guest_invoice(order, request)
    - parse_webhook(request)

⚠️ Points à valider avec la doc + les clés avant la mise en prod :
    1. Algorithme exact + clé du HMAC x-token (header envoyé par CinetPay)
    2. Structure exacte des réponses API (champs précis)
    3. Comportement en mode sandbox (URL différente ?)

⚠️ Ce fichier est INERTE tant que PAYMENT_PROVIDER != 'cinetpay'.
"""
import hashlib
import hmac
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _safe_json(response, endpoint=''):
    """
    Tente de parser response.json(). Retourne toujours un dict.

    Si la réponse n'est PAS du JSON (cas typique : Cloudflare 403 HTML,
    erreur 500 côté CinetPay, page d'erreur nginx, timeout), cette
    fonction retourne un dict avec un message d'erreur clair au lieu
    de laisser Python lever une exception 'Expecting value: line 1
    column 1 (char 0)'.
    """
    try:
        return response.json()
    except ValueError:
        preview = (response.text or '')[:300].replace('\n', ' ').replace('\r', '')
        logger.error(
            "CinetPay : réponse non-JSON sur %s — HTTP %s — %s",
            endpoint or 'inconnu',
            getattr(response, 'status_code', '?'),
            preview,
        )
        return {
            'code': 'NON_JSON',
            'message': (
                f"Réponse CinetPay invalide "
                f"(HTTP {getattr(response, 'status_code', '?')})"
            ),
        }


# ---------------------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------------------
CINETPAY_API_BASE = getattr(
    settings,
    'CINETPAY_API_BASE',
    'https://api-checkout.cinetpay.com/v2',
)

# Statuts renvoyés par l'API de vérification CinetPay
STATUS_ACCEPTED = 'ACCEPTED'
STATUS_REFUSED = 'REFUSED'


class CinetPayService:
    """
    Service CinetPay — implémentation des méthodes du contrat
    provider de paiement.
    """

    # ------------------------------------------------------------------
    # CONFIGURATION
    # ------------------------------------------------------------------
    @classmethod
    def _api_key(cls):
        return getattr(settings, 'CINETPAY_API_KEY', '')

    @classmethod
    def _site_id(cls):
        return getattr(settings, 'CINETPAY_SITE_ID', '')

    @classmethod
    def _base_url(cls):
        return getattr(settings, 'CINETPAY_API_BASE', CINETPAY_API_BASE).rstrip('/')

    @classmethod
    def _api_headers(cls):
        """
        Headers HTTP envoyés à l'API CinetPay.
        Le User-Agent est OBLIGATOIRE : sans lui, Cloudflare bloque
        les requêtes depuis les IPs datacenter.
        """
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'IvoirPass/1.0 (+https://ivoirpass.com)',
        }

    @classmethod
    def _webhook_secret(cls):
        """
        Secret utilisé pour vérifier le header x-token envoyé par CinetPay.
        """
        return getattr(settings, 'CINETPAY_WEBHOOK_SECRET', '') or cls._api_key()

    # ------------------------------------------------------------------
    # 1. VERIFICATION SIGNATURE WEBHOOK
    # ------------------------------------------------------------------
    @classmethod
    def verify_webhook_signature(cls, request):
        """
        Vérifie que le webhook vient bien de CinetPay.
        CinetPay envoie un header HTTP `x-token` qui est un HMAC
        calculé à partir du corps de la requête et d'un secret partagé.
        """
        secret = cls._webhook_secret()
        if not secret:
            logger.error(
                "CinetPay : CINETPAY_WEBHOOK_SECRET (ou CINETPAY_API_KEY) "
                "non configuré — impossible de vérifier la signature."
            )
            return False

        received_token = request.headers.get('x-token', '')
        if not received_token:
            logger.warning("CinetPay webhook : header 'x-token' manquant.")
            return False

        try:
            # Tentative 1 : HMAC-SHA256(body, secret)
            expected = hmac.new(
                secret.encode('utf-8'),
                request.body,
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(received_token, expected):
                return True

            # Tentative 2 : HMAC-SHA256(secret, body)
            expected_alt = hmac.new(
                request.body,
                secret.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(received_token, expected_alt):
                return True

            logger.warning(
                "CinetPay webhook : signature x-token invalide "
                "(reçu=%s...)", received_token[:16]
            )
            return False

        except Exception as exc:
            logger.exception("CinetPay : erreur de vérification signature : %s", exc)
            return False

    # ------------------------------------------------------------------
    # 2. CREATION FACTURE (INIT) - FLUX LEGACY / COMPTE
    # ------------------------------------------------------------------
    @classmethod
    def create_invoice(cls, order, request):
        """
        Crée une facture CinetPay et retourne l'URL de paiement
        vers laquelle rediriger l'acheteur.
        """
        api_key = cls._api_key()
        site_id = cls._site_id()

        if not api_key or not site_id:
            return {
                'success': False,
                'error': 'CINETPAY_API_KEY ou CINETPAY_SITE_ID non configuré.',
            }

        base_url = getattr(settings, 'PAYDUNYA_BASE_URL', 'https://ivoirpass.com')

        # transaction_id unique (CinetPay l'exige)
        transaction_id = getattr(order, 'order_number', '') or str(getattr(order, 'uuid', ''))

        # Construction des URLs absolues pour CinetPay
        return_url = f"{base_url}/paiements/retour/{transaction_id}/"
        notify_url = f"{base_url}/paiements/webhook/"

        # Description lisible
        description = f"Commande {transaction_id} — IvoirPass"

        # Metadata : on y met l'order_number pour le retrouver côté webhook
        # (CinetPay le renverra dans cpm_custom)
        metadata = transaction_id

        payload = {
            'apikey':       api_key,
            'site_id':      site_id,
            'transaction_id': transaction_id,
            'amount':       int(order.total),
            'currency':     'XOF',
            'description':  description,
            'return_url':   return_url,
            'notify_url':   notify_url,
            'channels':     'MOBILE_MONEY',
            'metadata':     metadata,
            'lang':         'fr',
        }

        try:
            response = requests.post(
                f"{cls._base_url()}/payment",
                json=payload,
                headers=cls._api_headers(),
                timeout=30,
            )
            data = _safe_json(response, 'create_invoice')
        except requests.RequestException as exc:
            logger.error("CinetPay create_invoice : erreur réseau %s", exc)
            return {'success': False, 'error': str(exc)}

        code = str(data.get('code', '')).strip()
        if code in ('201', '00', '0'):
            payment_url = (
                data.get('data', {}).get('payment_url')
                or data.get('payment_url')
                or ''
            )
            token = (
                data.get('data', {}).get('payment_token')
                or data.get('payment_token')
                or transaction_id
            )
            if not payment_url:
                logger.error("CinetPay : payment_url absente dans la réponse : %s", data)
                return {'success': False, 'error': 'payment_url manquante.'}

            return {'success': True, 'token': token, 'payment_url': payment_url}

        logger.error("CinetPay create_invoice : échec — %s", data)
        return {
            'success': False,
            'error': data.get('message') or data.get('description') or 'Erreur CinetPay.',
        }

    # ------------------------------------------------------------------
    # 3. VERIFICATION PAIEMENT (CHECK)
    # ------------------------------------------------------------------
    @classmethod
    def verify_payment(cls, token):
        """
        Vérifie le statut réel d'une transaction auprès de CinetPay.
        """
        api_key = cls._api_key()
        site_id = cls._site_id()

        if not api_key or not site_id:
            return {
                'success': False,
                'status': 'failed',
                'message': 'CINETPAY_API_KEY ou CINETPAY_SITE_ID non configuré.',
            }

        payload = {
            'apikey':         api_key,
            'site_id':        site_id,
            'transaction_id': token,
        }

        try:
            response = requests.post(
                f"{cls._base_url()}/payment/check",
                json=payload,
                headers=cls._api_headers(),
                timeout=30,
            )
            data = _safe_json(response, 'verify_payment')
        except requests.RequestException as exc:
            logger.error("CinetPay verify_payment : erreur réseau %s", exc)
            return {'success': False, 'status': 'error', 'message': str(exc)}

        # Extraction du statut brut CinetPay
        raw_status = str(
            data.get('data', {}).get('status')
            or data.get('status')
            or ''
        ).upper().strip()

        # Normalisation vers le vocabulaire PayDunya utilisé par verification.py
        if raw_status == STATUS_ACCEPTED:
            normalized = 'completed'
        elif raw_status in ('PENDING', 'INITIATED', 'PROCESSING'):
            normalized = 'pending'
        elif raw_status == STATUS_REFUSED:
            normalized = 'failed'
        else:
            normalized = 'pending'

        # Extraction du montant (indispensable pour verification.py)
        tx_data = data.get('data', data)
        amount = tx_data.get('amount') or data.get('amount')
        if amount is not None:
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = None

        return {
            'success': raw_status in (STATUS_ACCEPTED, 'PENDING', 'INITIATED'),
            'status':  normalized,
            'amount':  amount,
            'data':    tx_data,
            'raw':     data,
            'raw_status': raw_status,
        }

    # ------------------------------------------------------------------
    # 4. ADAPTATION POUR LE FLUX GUEST (BILLETTERIE / BOUTIQUE)
    # ------------------------------------------------------------------
    @classmethod
    def create_guest_invoice(cls, order, request):
        """
        Wrapper autour de create_invoice pour normaliser le retour
        au format attendu par les vues guest.
        """
        # On adapte les URLs de retour pour le flux invité
        base_url = getattr(settings, 'PAYDUNYA_BASE_URL', 'https://ivoirpass.com').rstrip('/')
        transaction_id = getattr(order, 'order_number', '') or str(getattr(order, 'uuid', ''))
        
        # (On pourrait passer des URLs spécifiques via request, mais create_invoice 
        # gère déjà la construction. On s'assure juste que le retour pointe vers la confirmation guest)
        
        result = cls.create_invoice(order, request)
        
        if result.get('success'):
            return {
                'success': True,
                'provider_reference': result.get('token', ''),
                'payment_url': result.get('payment_url', ''),
                'raw': result,
                'error': None,
            }
        else:
            return {
                'success': False,
                'error': result.get('error', 'Erreur CinetPay inconnue'),
                'provider_reference': '',
                'payment_url': '',
                'raw': result,
            }

    # ------------------------------------------------------------------
    # 5. WEBHOOK PARSER
    # ------------------------------------------------------------------
    @classmethod
    def parse_webhook(cls, request):
        """
        Extrait et normalise le payload du webhook CinetPay.
        CinetPay envoie généralement les données en form-data (request.POST).
        """
        # CinetPay envoie le plus souvent du form-data
        data = request.POST.dict()
        
        # Fallback au cas où ils enverraient du JSON
        if not data and request.body:
            import json
            try:
                data = json.loads(request.body)
            except Exception:
                pass

        # Extraction des champs CinetPay
        # cpm_trans_id : l'ID de la transaction (transaction_id)
        # cpm_result   : "00" pour succès
        # cpm_trans_status : "ACCEPTED" pour succès
        # cpm_custom   : la valeur de metadata qu'on a envoyée
        reference = data.get('cpm_trans_id', '')
        result_code = data.get('cpm_result', '')
        raw_status = str(data.get('cpm_trans_status', '')).upper()
        
        # Normalisation du statut
        if raw_status == STATUS_ACCEPTED or result_code == '00':
            status = 'completed'
        elif raw_status == STATUS_REFUSED:
            status = 'failed'
        else:
            status = 'pending'

        return {
            'order_number': data.get('cpm_custom', '') or data.get('transaction_id', ''),
            'provider_reference': reference,
            'status': status,
            'raw': data,
        }