"""
IvoirPass V2 — Vérification des paiements PayDunya.

Ce module centralise la vérification défensive des webhooks PayDunya :
- comparaison du montant reçu avec le montant attendu de la commande
- vérification que le token PayDunya est bien lié à la commande reçue

Utilisé par les 4 webhooks de l'application :
  - apps/payments/views.py::payment_webhook          (Order)
  - apps/tickets/views.py::guest_webhook             (GuestOrder)
  - apps/store/views.py::store_webhook               (ProductOrder)
  - apps/store/views.py::guest_store_webhook         (GuestProductOrder)

En mode test (PAYDUNYA_MODE == 'test'), la vérification est ignorée :
l'API PayDunya ne renvoie pas les mêmes données dans ce mode et la
signature du webhook reste vérifiée séparément.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings


logger = logging.getLogger(__name__)


def _extract_amount(data):
    """
    Tente d'extraire le montant depuis la réponse PayDunya.
    Retourne un Decimal, ou None si introuvable.

    On essaie plusieurs emplacements car PayDunya peut faire évoluer
    la structure de sa réponse (invoice.total_amount étant le chemin
    documenté, mais on ne veut pas échouer si le champ est renommé).
    """
    if not isinstance(data, dict):
        return None

    invoice = data.get('invoice')
    candidates = []
    if isinstance(invoice, dict):
        candidates.append(invoice.get('total_amount'))
        candidates.append(invoice.get('total'))
    candidates.append(data.get('total_amount'))
    candidates.append(data.get('total'))

    for candidate in candidates:
        if candidate is None or candidate == '':
            continue
        try:
            return Decimal(str(candidate).strip())
        except (InvalidOperation, ValueError, TypeError):
            continue
    return None


def _order_matches_payment(payment, expected_order):
    """
    Vérifie que le Payment pointe bien vers expected_order.
    Retourne True/False.
    """
    # Imports locaux pour éviter tout import circulaire au chargement du module.
    from apps.tickets.models import Order, GuestOrder
    from apps.store.models import ProductOrder, GuestProductOrder

    if isinstance(expected_order, Order):
        return payment.order_id == expected_order.id
    if isinstance(expected_order, GuestOrder):
        return payment.guest_order_id == expected_order.id
    if isinstance(expected_order, ProductOrder):
        return payment.product_order_id == expected_order.id
    if isinstance(expected_order, GuestProductOrder):
        return payment.guest_product_order_id == expected_order.id
    return False


def verify_payment_amount_and_binding(verify_result, expected_order, token):
    """
    Vérifie que le montant PayDunya correspond à la commande attendue
    et que le token PayDunya est bien lié à cette commande.

    Paramètres
    ----------
    verify_result : dict
        Réponse de PayDunyaService.verify_payment(token).
        Exemple : {'success': True, 'status': 'completed', 'data': {...}}
    expected_order : Order | GuestOrder | ProductOrder | GuestProductOrder
        La commande Django à confirmer.
    token : str
        Le token PayDunya issu du webhook.

    Retour
    ------
    dict avec les clés :
      - ok (bool)             : True si toutes les vérifications passent
      - reason (str)          : 'ok', 'test_mode_skip', 'token_missing',
                                'amount_missing', 'amount_expected_missing',
                                'amount_mismatch', 'payment_not_found',
                                'binding_mismatch'
      - expected (Decimal|None) : montant attendu (order.total)
      - received (Decimal|None) : montant reçu de PayDunya

    Cette fonction ne lève JAMAIS d'exception : toute erreur inattendue
    est convertie en retour {'ok': False, ...}.
    """
    result = {
        'ok': True,
        'reason': 'ok',
        'expected': None,
        'received': None,
    }

    try:
        # 1. Mode test : PayDunya ne renvoie pas les mêmes données.
        #    La signature du webhook reste vérifiée séparément dans les vues.
        if getattr(settings, 'PAYDUNYA_MODE', '') == 'test':
            result['reason'] = 'test_mode_skip'
            return result

        # 2. Token absent : anomalie, on refuse.
        if not token:
            result['ok'] = False
            result['reason'] = 'token_missing'
            return result

        # 3. Extraction du montant attendu et reçu.
        expected = getattr(expected_order, 'total', None)
        if expected is not None:
            try:
                expected = Decimal(str(expected))
            except (InvalidOperation, ValueError, TypeError):
                expected = None

        data = (verify_result or {}).get('data') or {}
        received = _extract_amount(data)

        result['expected'] = expected
        result['received'] = received

        # 4. Montant reçu introuvable : on ne peut pas vérifier → on refuse.
        if received is None:
            result['ok'] = False
            result['reason'] = 'amount_missing'
            return result

        # 5. Montant attendu introuvable côté commande : anomalie → on refuse.
        if expected is None:
            result['ok'] = False
            result['reason'] = 'amount_expected_missing'
            return result

        # 6. Comparaison stricte (Decimal == Decimal ignore l'échelle,
        #    donc Decimal('5000') == Decimal('5000.00') → True).
        if received != expected:
            result['ok'] = False
            result['reason'] = 'amount_mismatch'
            return result

        # 7. Binding : le token doit correspondre à un Payment lié à cette commande.
        from apps.payments.models import Payment
        payment = Payment.objects.filter(paydunya_token=token).first()
        if payment is None:
            result['ok'] = False
            result['reason'] = 'payment_not_found'
            return result

        if not _order_matches_payment(payment, expected_order):
            result['ok'] = False
            result['reason'] = 'binding_mismatch'
            return result

        return result

    except Exception as exc:
        # Filet de sécurité : ne jamais laisser une exception remonter depuis
        # un check de sécurité, sous peine de faire planter la vue webhook.
        logger.exception("verify_payment_amount_and_binding: erreur inattendue — %s", exc)
        result['ok'] = False
        result['reason'] = f'unexpected_error: {exc}'
        return result
