"""
IvoirPass V2 — Adaptateur allauth personnalisé
Restreint l'inscription publique tout en gardant le formulaire pour les organisateurs
"""
from allauth.account.adapter import DefaultAccountAdapter


class NoPublicSignupAdapter(DefaultAccountAdapter):
    """
    L'inscription reste techniquement active (nécessaire pour créer
    des comptes organisateurs) mais n'est plus accessible depuis
    la navigation publique. Seul le lien direct /accounts/signup/
    fonctionne encore pour les organisateurs qui le connaissent.
    """
    def is_open_for_signup(self, request):
        return True  # Reste ouvert techniquement, juste plus dans la nav