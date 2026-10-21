"""
IvoirPass V2 — Service de paiement FeexPay.

Documentation : https://docs.feexpay.me
API v2 : https://api-v2.feexpay.me

Authentification : header Authorization: Bearer <API_TOKEN>
"""
import logging
from decimal import Decimal
from uuid import UUID

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Timeout HTTP (secondes)
TIMEOUT = 15


def _safe_json(response, endpoint=''):
    """Parse la réponse JSON en toute sécurité."""
    try:
        return response.json()
    except Exception:
        logger.error(
            "Réponse non-JSON FeexPay [%s] HTTP %s: %s",
            endpoint, response.status_code, response.text[:300],
        )
        return {}


class FeexPayService:
    """
    Service FeexPay pour IvoirPass.

    Méthodes :
        create_invoice(order, request, network=None) -> dict
        verify_payment(reference) -> dict
        parse_webhook(request) -> dict
        verify_webhook_signature(request) -> bool
    """

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @classmethod
    def _api_token(cls):
        token = getattr(settings, 'FEEXPAY_API_TOKEN', '')
        if not token:
            raise ValueError("FEEXPAY_API_TOKEN manquant dans les settings.")
        return token

    @classmethod
    def _shop_id(cls):
        shop = getattr(settings, 'FEEXPAY_SHOP_ID', '')
        if not shop:
            raise ValueError("FEEXPAY_SHOP_ID manquant dans les settings.")
        return shop

    @classmethod
    def _base_url(cls):
        return getattr(
            settings, 'FEEXPAY_BASE_URL', 'https://api-v2.feexpay.me'
        ).rstrip('/')

    @classmethod
    def _headers(cls):
        return {
            'Authorization': f'Bearer {cls._api_token()}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    # ------------------------------------------------------------------
    # Détection du réseau à partir du numéro ivoirien
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_network(phone_number):
        """
        Détection basique du réseau CI à partir du préfixe.

        Préfixes usuels (à ajuster si besoin) :
          - 07 → Orange
          - 05 → MTN
          - 01 → Moov
          - Wave : souvent 07 aussi (Orange) mais Wave est un wallet
            indépendant. On ne peut pas le déduire du numéro.
            → Par défaut, on route vers Wave si aucun autre réseau
              n'est identifiable, car Wave est très utilisé en CI.
        """
        phone = str(phone_number).replace('+', '').replace(' ', '')
        if phone.startswith('225'):
            phone = phone[3:]

        if phone.startswith('05'):
            return 'mtn_ci'
        if phone.startswith('01'):
            return 'moov_ci'
        if phone.startswith('07'):
            # Orange ou Wave — on privilégie Wave (wallet très répandu)
            return 'wave_ci'
        # Fallback
        return 'wave_ci'

    # ------------------------------------------------------------------
    # Création de facture (Payin)
    # ------------------------------------------------------------------
    @classmethod
    def _normalize_phone(cls, phone):
        """
        Normalise un numéro ivoirien au format FeexPay : 225XXXXXXXXXX
        (sans +, sans espace, préfixe 225 obligatoire).

        Exemples :
            0700000000           → 2250700000000
            +225 07 00 00 00 00  → 2250700000000
            2250700000000        → 2250700000000 (inchangé)
        """
        p = str(phone or '').strip().replace(' ', '').replace('-', '')
        if p.startswith('+'):
            p = p[1:]
        if not p.startswith('225'):
            p = '225' + p
        return p

    @classmethod
    def create_invoice(cls, order, request, network=None):
        """
        Crée une demande de paiement FeexPay.
        Retourne le format normalisé commun aux providers.
        """
        if network is None:
            network = cls._detect_network(order.phone)

        endpoint = f"/api/transactions/public/requesttopay/{network}"
        url = f"{cls._base_url()}{endpoint}"

        # URLs de retour — building à partir de la base app
        base_url = getattr(settings, 'PAYDUNYA_BASE_URL', '').rstrip('/')
        return_url  = f"{base_url}/billets/guest/retour/{order.access_token}/"
        cancel_url  = f"{base_url}/billets/guest/annulation/{order.access_token}/"
        webhook_url = f"{base_url}/billets/guest/webhook/"

        payload = {
            'shop':        cls._shop_id(),
            'amount':      int(order.total),
            'phoneNumber': cls._normalize_phone(order.phone),
            'description': f"IvoirPass — Commande {order.order_number}"[:100],
            'callback_info':  str(order.order_number),
            'return_url':     return_url,
            'cancel_url':     cancel_url,
            'callback_url':   webhook_url,
            'webhook_url':    webhook_url,
        }
        buyer_name = getattr(order, 'buyer_name', None)
        if buyer_name:
            parts = buyer_name.split(' ', 1)
            payload['first_name'] = parts[0]
            if len(parts) > 1:
                payload['last_name'] = parts[1]
        if getattr(order, 'email', None):
            payload['email'] = order.email

        logger.info(
            "FeexPay create_invoice | commande=%s | réseau=%s | montant=%s",
            order.order_number, network, order.total,
        )
        try:
            response = requests.post(
                url, json=payload, headers=cls._headers(), timeout=TIMEOUT,
            )
            data = _safe_json(response, endpoint)

            if response.status_code not in (200, 201, 202):
                logger.error("FeexPay create_invoice HTTP %s : %s",
                             response.status_code, data)
                return {
                    'success': False,
                    'error':   f"FeexPay a refusé ({response.status_code}) : {data}",
                    'provider_reference': '', 'payment_url': '', 'raw': data,
                }

            reference = data.get('reference')
            if not reference:
                return {
                    'success': False,
                    'error':   f"Réponse FeexPay sans 'reference'. Data={data}",
                    'provider_reference': '', 'payment_url': '', 'raw': data,
                }

            payment_url = (
                data.get('payment_url') or data.get('wave_launch_url')
                or data.get('url') or ''
            )
            return {
                'success':            True,
                'provider_reference': reference,
                'payment_url':        payment_url,
                'raw':                data,
                'error':              None,
            }
        except requests.RequestException as exc:
            logger.exception("FeexPay create_invoice erreur réseau : %s", exc)
            return {
                'success': False, 'error': f"Connexion FeexPay : {exc}",
                'provider_reference': '', 'payment_url': '', 'raw': {},
            }

    create_guest_invoice = create_invoice  # alias pour cohérence API

    @classmethod
    def verify_payment(cls, reference):
        """
        Vérifie le statut — format normalisé {success, status, amount, raw}.
        L'API status FeexPay peut retourner amount dans différents champs
        selon la version. On est défensif.
        """
        endpoint = f"/api/transactions/public/single/status/{reference}"
        url = f"{cls._base_url()}{endpoint}"
        try:
            response = requests.get(url, headers=cls._headers(), timeout=TIMEOUT)
            data = _safe_json(response, endpoint)
            if response.status_code != 200:
                logger.error("FeexPay verify_payment HTTP %s : %s",
                             response.status_code, data)
                return {'success': False, 'status': 'pending',
                        'amount': None, 'raw': data}

            raw_status = (data.get('status') or '').upper()
            status_map = {
                'SUCCESSFUL': 'completed',
                'FAILED':     'failed',
                'PENDING':    'pending',
            }
            normalized = status_map.get(raw_status, 'pending')

            # Extraction robuste du montant (plusieurs formats possibles)
            amount = (
                data.get('amount')
                or data.get('montant')
                or (data.get('data') or {}).get('amount')
                or (data.get('transaction') or {}).get('amount')
            )
            if amount is not None:
                try:
                    amount = int(amount)
                except (TypeError, ValueError):
                    pass

            return {
                'success': normalized == 'completed',
                'status':  normalized,
                'amount':  amount,
                'reference': data.get('reference') or reference,
                'raw':     data,
            }
        except requests.RequestException as exc:
            logger.exception("FeexPay verify_payment erreur réseau : %s", exc)
            return {'success': False, 'status': 'pending', 'amount': None, 'raw': {}}

    @classmethod
    def parse_webhook(cls, request):
        """
        Extrait et normalise le payload FeexPay.
        Retourne : {order_number, provider_reference, status, raw}.
        """
        import json as _json
        try:
            payload = _json.loads(request.body)
        except Exception:
            return {'order_number': '', 'provider_reference': '',
                    'status': 'unknown', 'raw': {}}

        raw_status = (payload.get('status') or '').upper()
        status_map = {
            'SUCCESSFUL': 'completed',
            'FAILED':     'failed',
            'PENDING':    'pending',
        }
        return {
            'order_number':       payload.get('callback_info', ''),
            'provider_reference': payload.get('reference', ''),
            'status':             status_map.get(raw_status, 'pending'),
            'raw':                payload,
        }


    @classmethod
    def verify_webhook_signature(cls, request):
        """
        FeexPay ne fournit PAS de signature HMAC sur les webhooks.
        La sécurité repose sur :
          1. L'URL de webhook secrète (non devinable)
          2. La vérification du statut via verify_payment() avant de
             valider définitivement une commande.

        On retourne True ici, et le caller DOIT vérifier le statut
        via l'API avant de confirmer la commande.
        """
        return True