"""
IvoirPass V2 — Service PayDunya
"""
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class PayDunyaService:
    """Service pour interagir avec l'API PayDunya."""

    @classmethod
    def verify_webhook_signature(cls, request):
        """Vérifie le hash SHA-512 du webhook PayDunya."""
        import hashlib
        import hmac
        import json

        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return False

        received_hash = body.get('hash', '') or body.get('data', {}).get('hash', '')
        if not received_hash:
            return False

        expected_hash = hashlib.sha512(
            settings.PAYDUNYA_MASTER_KEY.encode('utf-8')
        ).hexdigest()

        return hmac.compare_digest(received_hash, expected_hash)

    @classmethod
    def get_headers(cls):
        return {
            'Content-Type': 'application/json',
            'PAYDUNYA-MASTER-KEY': settings.PAYDUNYA_MASTER_KEY,
            'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
            'PAYDUNYA-TOKEN': settings.PAYDUNYA_TOKEN,
        }

    @classmethod
    def create_invoice(cls, order, request):
        """
        Crée une facture PayDunya pour une commande de billets et renvoie
        l'URL de paiement hébergée sur laquelle rediriger l'acheteur
        (méthode par redirection — l'acheteur paie sur le site PayDunya,
        pas sur IvoirPass directement).

        Returns:
            dict : {'success': bool, 'token': str, 'payment_url': str}
                   ou {'success': False, 'error': str} en cas d'échec.
        """
        base_url    = settings.PAYDUNYA_BASE_URL
        return_url  = f"{base_url}/paiements/retour/{order.order_number}/"
        cancel_url  = f"{base_url}/paiements/annulation/{order.order_number}/"
        webhook_url = f"{base_url}/paiements/webhook/"

        items = {}
        for i, item in enumerate(order.items.all(), start=1):
            items[f"item_{i}"] = {
                "name":        item.ticket_type.name,
                "quantity":    item.quantity,
                "unit_price":  str(item.unit_price),
                "total_price": str(item.unit_price * item.quantity),
                "description": f"Billet {item.ticket_type.event.title}",
            }

        payload = {
            "store": {
                "name":        "IvoirPass",
                "tagline":     "Billetterie événementielle",
                "website_url": base_url,
            },
            "invoice": {
                "items": items,
                "total_amount": str(int(order.total)),
                "description":  f"Commande {order.order_number}",
            },
            "actions": {
                "cancel_url":   cancel_url,
                "return_url":   return_url,
                "callback_url": webhook_url,
            },
            "custom_data": {
                "order_number": order.order_number,
                "buyer_email":  order.buyer.email,
            }
        }

        try:
            response = requests.post(
                settings.PAYDUNYA_API_BASE + '/checkout-invoice/create',
                json=payload,
                headers=cls.get_headers(),
                timeout=30,
            )
            data = response.json()

            if data.get('response_code') == '00':
                return {
                    'success':     True,
                    'token':       data['token'],
                    'payment_url': data['response_text'],
                }
            else:
                logger.error(f"Échec création facture PayDunya : {data}")
                return {
                    'success': False,
                    'error':   data.get('response_text', 'Erreur PayDunya inconnue'),
                }

        except Exception as e:
            logger.error(f"Erreur connexion PayDunya (create_invoice) : {e}")
            return {'success': False, 'error': str(e)}

    DISBURSEMENT_MODES = {
        'wave': 'wave-ci',
        'orange_money': 'orange-money-ci',
        'mtn_momo': 'mtn-ci',
        'moov': 'moov-ci',
    }

    @classmethod
    def _disbursement_headers(cls):
        return cls.get_headers()

    @classmethod
    def _disbursement_callback_url(cls):
        return f"{settings.PAYDUNYA_BASE_URL.rstrip('/')}/dashboard/reversement/paydunya/webhook/"

    @classmethod
    def create_disbursement(cls, withdrawal):
        "Crée une facture de décaissement PayDunya."
        mode = cls.DISBURSEMENT_MODES.get(withdrawal.payout_method)
        if not mode:
            return {'success': False, 'error': 'Méthode Mobile Money non supportée'}
        phone = ''.join(ch for ch in withdrawal.payout_phone if ch.isdigit())
        if phone.startswith('225'):
            phone = phone[3:]
        payload = {
            'account_alias': phone,
            'amount': int(withdrawal.amount_net or withdrawal.amount),
            'withdraw_mode': mode,
            'callback_url': cls._disbursement_callback_url(),
        }
        try:
            response = requests.post(
                f"{settings.PAYDUNYA_DISBURSEMENT_API_BASE.rstrip('/')}/disburse/get-invoice",
                json=payload,
                headers=cls._disbursement_headers(),
                timeout=30,
            )
            data = response.json()
            if data.get('response_code') == '00' and data.get('disburse_token'):
                return {'success': True, 'token': data['disburse_token'], 'status': 'created'}
            return {'success': False, 'error': data.get('response_text', 'Erreur PayDunya lors de la création du payout')}
        except Exception as exc:
            logger.exception('Erreur création payout PayDunya pour %s', withdrawal.reference)
            return {'success': False, 'error': str(exc)}

    @classmethod
    def submit_disbursement(cls, token, disburse_id):
        try:
            response = requests.post(
                f"{settings.PAYDUNYA_DISBURSEMENT_API_BASE.rstrip('/')}/disburse/submit-invoice",
                json={'disburse_invoice': token, 'disburse_id': disburse_id},
                headers=cls._disbursement_headers(),
                timeout=30,
            )
            data = response.json()
            return {
                'success': data.get('response_code') == '00',
                'status': (data.get('status') or ('success' if data.get('response_code') == '00' and 'pending' not in str(data.get('response_text','')).lower() else 'pending')).lower(),
                'transaction_id': data.get('transaction_id', ''),
                'provider_ref': data.get('provider_ref', ''),
                'response_text': data.get('response_text', ''),
                'error': data.get('response_text', 'Erreur PayDunya'),
            }
        except Exception as exc:
            logger.exception('Erreur submit payout PayDunya %s', disburse_id)
            return {'success': False, 'status': 'unknown', 'error': str(exc)}

    @classmethod
    def check_disbursement_status(cls, token):
        try:
            response = requests.post(
                f"{settings.PAYDUNYA_DISBURSEMENT_API_BASE.rstrip('/')}/disburse/check-status",
                json={'disburse_invoice': token},
                headers=cls._disbursement_headers(),
                timeout=30,
            )
            data = response.json()
            return {
                'success': data.get('response_code') == '00',
                'status': (data.get('status') or 'failed').lower(),
                'transaction_id': data.get('transaction_id', ''),
                'disburse_tx_id': data.get('disburse_tx_id', ''),
                'response_text': data.get('response_text', ''),
                'error': data.get('response_text', 'Erreur PayDunya'),
            }
        except Exception as exc:
            logger.exception('Erreur check status payout PayDunya')
            return {'success': False, 'status': 'unknown', 'error': str(exc)}

    @classmethod
    def parse_disbursement_callback(cls, request):
        import json
        try:
            return json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    @classmethod
    def verify_disbursement_callback(cls, payload):
        import hashlib, hmac
        received = payload.get('hash', '')
        expected = hashlib.sha512(settings.PAYDUNYA_MASTER_KEY.encode('utf-8')).hexdigest()
        return bool(received) and hmac.compare_digest(received, expected)

    @classmethod
    def verify_payment(cls, token):
        """
        Vérifie le statut d'un paiement PayDunya.
        """
        # ✅ MODE TEST : Accepter les tokens "test_" UNIQUEMENT en mode test
        if token and token.startswith('test_'):
            if settings.PAYDUNYA_MODE == 'test':
                logger.info(f"Mode TEST - Paiement accepté pour {token}")
                return {
                    'success': True,
                    'status': 'completed',
                    'message': 'Test payment successful'
                }
            else:
                logger.warning(f"Token test_ rejeté en mode production: {token}")
                return {
                    'success': False,
                    'status': 'failed',
                    'message': 'Test tokens not allowed in production'
                }

        try:
            url = f"{settings.PAYDUNYA_API_BASE}/checkout-invoice/confirm/{token}"
            headers = cls.get_headers()
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('response_code') == '00':
                invoice = data.get('data', {}).get('invoice', {})
                status = invoice.get('status', '')
                
                return {
                    'success': True,
                    'status': status,
                    'data': data.get('data', {}),
                }
            else:
                return {
                    'success': False,
                    'status': 'failed',
                    'message': data.get('response_text', 'Erreur PayDunya'),
                }
                
        except Exception as e:
            logger.error(f"Erreur vérification PayDunya: {e}")
            return {
                'success': False,
                'status': 'error',
                'message': str(e),
            }