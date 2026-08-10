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