"""
IvoirPass V2 — Service central de journalisation d'audit métier.

Point d'entrée UNIQUE utilisé par les autres apps (payments, tickets,
notifications, scanner...) pour écrire dans AuditLog. Centraliser ici évite
que chaque app réinvente sa propre façon de logger, et garantit deux
garanties valables PARTOUT :

1. Une erreur d'écriture d'audit ne doit JAMAIS faire échouer le flux
   métier appelant (un paiement confirmé doit rester confirmé même si,
   par exemple, la base d'audit est temporairement indisponible).
2. Aucune donnée sensible (tokens, mots de passe, clés API, codes OTP...)
   ne doit pouvoir se retrouver dans `description` ou `metadata`, même par
   erreur d'un appelant — on filtre activement avant écriture.
"""
import logging

logger = logging.getLogger(__name__)

# Clés interdites dans `metadata`, quel que soit l'appelant — filtrées par
# correspondance partielle insensible à la casse (ex: "auth_token" et
# "PAYDUNYA_TOKEN" sont tous les deux bloqués par "token").
_FORBIDDEN_METADATA_KEY_FRAGMENTS = (
    'token', 'password', 'secret', 'key', 'otp', 'card', 'cvv', 'pin',
)


def _sanitize_metadata(metadata):
    """Retire récursivement toute clé qui ressemble à une donnée sensible."""
    if not metadata:
        return None
    if not isinstance(metadata, dict):
        # On n'accepte que des dictionnaires — tout autre type est ignoré
        # plutôt que de risquer d'enregistrer une donnée non maîtrisée.
        return None

    cleaned = {}
    for key, value in metadata.items():
        key_lower = str(key).lower()
        if any(fragment in key_lower for fragment in _FORBIDDEN_METADATA_KEY_FRAGMENTS):
            continue
        if isinstance(value, dict):
            value = _sanitize_metadata(value)
        cleaned[key] = value
    return cleaned or None


def log_action(action, description, user=None, obj=None, model_name='', object_id='',
                metadata=None, ip_address=None):
    """
    Écrit une entrée dans le journal d'audit métier (AuditLog).

    Args:
        action: une valeur de AuditLog.Action (ex: AuditLog.Action.PAYMENT_SUCCESS).
        description: phrase lisible par un humain, SANS donnée sensible.
        user: utilisateur à l'origine de l'action (peut être None, ex: webhook).
        obj: objet concerné (Order, GuestOrder, Payment, Ticket...). Si fourni,
             `model_name`/`object_id` en sont déduits automatiquement —
             fonctionne aussi bien pour les commandes "compte" que "invité",
             sans qu'il soit nécessaire d'unifier ces modèles.
        model_name / object_id: à fournir seulement si `obj` est absent.
        metadata: dict de contexte structuré (montant, devise, provider...).
        ip_address: adresse IP à l'origine de l'action, si pertinente.
    """
    try:
        from .models import AuditLog

        if obj is not None:
            model_name = obj.__class__.__name__
            # order_number est le plus lisible/consultable quand il existe
            # (Order, GuestOrder, Ticket, Payment...) ; à défaut, la PK.
            object_id = str(
                getattr(obj, 'order_number', None)
                or getattr(obj, 'ticket_number', None)
                or getattr(obj, 'reference', None)
                or getattr(obj, 'pk', '')
            )

        AuditLog.objects.create(
            user=user,
            action=action,
            model_name=model_name,
            object_id=object_id,
            description=description,
            metadata=_sanitize_metadata(metadata),
            ip_address=ip_address,
        )
    except Exception:
        # On ne remonte JAMAIS cette exception : un souci d'audit ne doit
        # jamais interrompre un paiement, une commande ou l'envoi d'un
        # billet. On journalise techniquement l'incident pour qu'il reste
        # visible (Sentry via la config LOGGING existante) sans casser le
        # flux appelant.
        logger.error("Échec d'écriture AuditLog pour l'action %s", action, exc_info=True)


def get_client_ip(request):
    """
    Extrait l'IP cliente d'une requête. Utilisée par le middleware et par
    les vues qui écrivent dans AuditLog.

    ⚠️ X-Forwarded-For n'est fiable que si le serveur est bien placé
    derrière un reverse-proxy de confiance (Nginx) qui écrase cet en-tête
    plutôt que de le transmettre tel quel — à vérifier côté infra.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
