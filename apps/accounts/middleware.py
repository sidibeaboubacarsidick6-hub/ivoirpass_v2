"""
IvoirPass V2 — Restriction d'accès pour les comptes agent scanner.

Un agent scanner (CustomUser.Role.SCANNER) ne doit avoir accès qu'à
l'application de scan (/scanner/app/, son API sous /api/scanner/, et les
endpoints de connexion/déconnexion qu'elle utilise) — jamais au reste du
site (tableau de bord, boutique, billetterie, admin...).

Avant ce correctif, un agent scanner pouvait se connecter directement via
/accounts/login/ (le formulaire du site principal) et naviguer partout où
son compte avait techniquement les permissions Django de le faire — ce
middleware ferme cet accès de façon centralisée, quelle que soit la vue.
"""
from django.shortcuts import redirect
from django.urls import reverse


# Préfixes d'URL toujours autorisés pour un agent scanner, même connecté.
_ALLOWED_PREFIXES = (
    '/scanner/',
    '/api/scanner/',
    '/static/',
    '/media/',
)
# Chemins exacts (hors préfixes ci-dessus) nécessaires au fonctionnement de
# l'app scanner elle-même : son formulaire de connexion/déconnexion intégré
# poste directement sur les vues allauth du site principal.
_ALLOWED_EXACT_PATHS = (
    '/accounts/login/',
    '/accounts/logout/',
    '/favicon.ico',
)


class ScannerAccessRestrictionMiddleware:
    """Redirige tout agent scanner qui tente d'accéder à une page hors de
    l'application de scan vers celle-ci, plutôt que de le laisser naviguer
    sur le reste du site."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is not None and user.is_authenticated and
            getattr(user, 'is_scanner_agent', False) and
            not self._is_allowed(request.path)
        ):
            return redirect(reverse('scanner:app'))
        return self.get_response(request)

    @staticmethod
    def _is_allowed(path):
        if path in _ALLOWED_EXACT_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in _ALLOWED_PREFIXES)
