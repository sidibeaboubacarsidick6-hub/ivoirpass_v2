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
    def get_headers(cls):
        return {
            'Content-Type': 'application/json',
            'PAYDUNYA-MASTER-KEY': settings.PAYDUNYA_MASTER_KEY,
            'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
            'PAYDUNYA-TOKEN': settings.PAYDUNYA_TOKEN,
        }

    @classmethod
    def verify_payment(cls, token):
        """
        Vérifie le statut d'un paiement PayDunya.
        """
        # ✅ MODE TEST : Accepter les tokens "test_"
        if token and token.startswith('test_'):
            logger.info(f"🔬 Mode TEST - Paiement accepté pour {token}")
            return {
                'success': True,
                'status': 'completed',
                'message': 'Test payment successful'
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