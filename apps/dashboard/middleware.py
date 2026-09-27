"""
IvoirPass V2 — Middleware de journalisation d'audit
"""
from .models import AuditLog
from .services import log_action, get_client_ip


class AuditLogMiddleware:
    """Enregistre automatiquement les actions importantes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Logger les connexions
        if request.path == '/accounts/login/' and request.method == 'POST' and request.user.is_authenticated:
            log_action(
                action=AuditLog.Action.LOGIN,
                description=f"Connexion de {request.user.email}",
                user=request.user,
                ip_address=get_client_ip(request),
            )

        return response

    @staticmethod
    def get_client_ip(request):
        # Conservé pour compatibilité si du code externe l'appelait déjà ;
        # la logique vit désormais dans apps.dashboard.services.get_client_ip.
        return get_client_ip(request)
