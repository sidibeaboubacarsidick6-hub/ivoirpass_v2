"""
IvoirPass V2 — Dispatcher du service de paiement.

Permet de basculer entre plusieurs fournisseurs de paiement
(PayDunya, CinetPay, ...) via la variable d'environnement
PAYMENT_PROVIDER, sans modifier le code des vues, tâches ou
webhooks.

Usage :
    from apps.payments.provider import get_payment_service

    service = get_payment_service()
    result = service.create_invoice(order, request)
    result = service.verify_payment(token)
    # ...

Le provider actif est défini dans .env :
    PAYMENT_PROVIDER=paydunya   # ou cinetpay
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def _load_paydunya():
    """Charge le service PayDunya."""
    from apps.payments.paydunya import PayDunyaService
    return PayDunyaService


def _load_cinetpay():
    """Charge le service CinetPay."""
    from apps.payments.cinetpay import CinetPayService
    return CinetPayService


# Mapping nom → fonction de chargement
# On utilise des fonctions (et non des imports directs) pour éviter
# de charger tous les providers au démarrage : si un module n'existe
# pas encore, ça ne casse pas le démarrage de Django.
_PROVIDERS = {
    'paydunya': _load_paydunya,
    'cinetpay': _load_cinetpay,
}


def get_payment_service():
    """
    Retourne la classe du service de paiement actif.

    Le provider est lu depuis settings.PAYMENT_PROVIDER.
    Retourne la classe (avec ses classmethods), à utiliser comme :
        service = get_payment_service()
        service.create_invoice(...)
        service.verify_payment(...)

    Lève ValueError si :
      - le provider est inconnu
      - le module du provider n'existe pas / est cassé
    """
    provider_name = getattr(settings, 'PAYMENT_PROVIDER', 'paydunya')
    provider_name = (provider_name or 'paydunya').lower().strip()

    loader = _PROVIDERS.get(provider_name)
    if loader is None:
        raise ValueError(
            f"PAYMENT_PROVIDER inconnu : '{provider_name}'. "
            f"Valeurs valides : {', '.join(sorted(_PROVIDERS.keys()))}"
        )

    try:
        return loader()
    except ImportError as exc:
        logger.exception(
            "Impossible de charger le service de paiement '%s'",
            provider_name,
        )
        raise ValueError(
            f"Le service de paiement '{provider_name}' n'est pas disponible "
            f"(module introuvable). Vérifiez que le fichier correspondant "
            f"existe dans apps/payments/."
        ) from exc


def get_provider_name():
    """Retourne le nom du provider actif (utile pour logs / templates)."""
    return getattr(settings, 'PAYMENT_PROVIDER', 'paydunya')
