"""
IvoirPass V2 — Service CinetPay.

Agrégateur de paiement agréé BCEAO en Côte d'Ivoire.
Supporte Orange Money, MTN MoMo, Moov Money, Wave.

API v2 Checkout :
    Init     : POST https://api-checkout.cinetpay.com/v2/payment
    Verify   : POST https://api-checkout.cinetpay.com/v2/payment/check

Ce module expose les 3 méthodes attendues par le dispatcher
(apps.payments.provider.get_payment_service) :
    - verify_webhook_signature(request)
    - create_invoice(order, request)
    - verify_payment(token)

⚠️ Points à valider avec la doc + les clés avant la mise en prod :
    1. Algorithme exact + clé du HMAC x-token (header envoyé par CinetPay)
    2. Structure exacte des réponses API (champs précis)
    3. Comportement en mode sandbox (URL différente ?)
    4. Couverture payout (hors périmètre aujourd'hui — reste sur PayDunya)

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
    Service CinetPay — implémentation des 3 méthodes du contrat
    provider de paiement.

    Toutes les méthodes sont des classmethods (comme PayDunyaService)
    pour rester compatibles avec le dispatcher.
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

        ⚠️ Le User-Agent est OBLIGATOIRE : sans lui, Cloudflare (pare-feu
        utilisé par de nombreux agrégateurs, dont PayDunya — CinetPay
        pourrait avoir la même politique) bloque les requêtes depuis
        les IPs datacenter (VPS, cloud) avec un 403.

        On garde 'Accept: application/json' pour garantir une réponse JSON.
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

        TODO : confirmer la source exacte avec le support CinetPay
        (docs.cinetpay.com, page notification). C'est probablement
        CINETPAY_API_KEY ou une clé dédiée fournie dans le dashboard.
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

        ⚠️ TODO : l'algorithme exact n'est pas documenté publiquement
        dans les pages accessibles. Deux hypothèses courantes :
            HMAC-SHA256(body, secret)
            HMAC-SHA256(secret, body)
        La méthode ci-dessous tente HMAC-SHA256(body, secret) — à
        ajuster après confirmation par le support CinetPay.

        Retourne True/False.
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
    # 2. CREATION FACTURE (INIT)
    # ------------------------------------------------------------------
    @classmethod
    def create_invoice(cls, order, request):
        """
        Crée une facture CinetPay et retourne l'URL de paiement
        vers laquelle rediriger l'acheteur.

        Paramètres :
            order   : Order, GuestOrder, ProductOrder ou GuestProductOrder
            request : HttpRequest (utilisé pour construire les URLs absolues)

        Retourne un dict :
            {'success': True,  'token': str, 'payment_url': str}
            {'success': False, 'error': str}
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
            'channels':     'MOBILE_MONEY',   # TODO : confirmer la valeur exacte
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

        # TODO : confirmer le code de succès exact côté CinetPay v2
        # (probablement 'code' == '201' ou '00' — à valider avec un vrai call sandbox)
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

        À appeler systématiquement après réception d'un webhook
        (règle CinetPay : ne jamais se fier à la seule notification).

        Paramètres :
            token : transaction_id envoyé à CinetPay (utilisé comme clé
                    de vérification via l'API /payment/check)

        Retourne un dict :
            {'success': True,  'status': 'completed'|'pending'|'failed', 'data': {...}}
            {'success': False, 'status': 'failed'|'error', 'message': str}

        Le champ 'status' est normalisé pour rester compatible avec
        l'appelant (verification.py attend 'completed' / 'pending' / autre).
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
            # ⚠️ On ne fait PAS raise_for_status() : Cloudflare peut renvoyer
            # un 403 HTML, on veut logger la vraie réponse avant d'échouer.
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

        # Normalisation vers le vocabulaire PayDunya utilisé par
        # verification.py : 'completed' / 'pending' / autre
        if raw_status == STATUS_ACCEPTED:
            normalized = 'completed'
        elif raw_status in ('PENDING', 'INITIATED', 'PROCESSING'):
            normalized = 'pending'
        elif raw_status == STATUS_REFUSED:
            normalized = 'failed'
        else:
            normalized = 'pending'  # par défaut, on n'affirme rien

        return {
            'success': raw_status in (STATUS_ACCEPTED, 'PENDING', 'INITIATED'),
            'status':  normalized,
            'data':    data.get('data', data),
            'raw_status': raw_status,
        }
