"""
IvoirPass V2 — Adaptateur allauth personnalisé
Inscription publique : réservée aux organisateurs uniquement.
"""
from allauth.account.adapter import DefaultAccountAdapter


class NoPublicSignupAdapter(DefaultAccountAdapter):
    """
    L'inscription est ouverte uniquement pour les organisateurs.
    Les participants achètent sans créer de compte (mode invité).
    """

    def is_open_for_signup(self, request):
        # L'inscription reste ouverte pour les organisateurs
        return True

    def save_user(self, request, user, form, commit=True):
        """
        Force le rôle 'organizer' pour tout nouvel inscrit.
        Les participants n'ont pas besoin de compte.
        """
        user = super().save_user(request, user, form, commit=False)
        user.role = 'organizer'
        if commit:
            user.save()
        return user
