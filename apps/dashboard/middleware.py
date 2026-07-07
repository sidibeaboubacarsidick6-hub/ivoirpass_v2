"""
IvoirPass V2 — Middleware de journalisation d'audit
"""
from .models import AuditLog


class AuditLogMiddleware:
    """Enregistre automatiquement les actions importantes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Logger les connexions
        if request.path == '/accounts/login/' and request.method == 'POST' and request.user.is_authenticated:
            AuditLog.objects.create(
                user=request.user,
                action=AuditLog.Action.LOGIN,
                description=f"Connexion de {request.user.email}",
                ip_address=self.get_client_ip(request),
            )

        return response

    @staticmethod
    def get_client_ip(request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')
