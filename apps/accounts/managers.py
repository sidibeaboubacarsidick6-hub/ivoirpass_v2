"""
IvoirPass V2 — Manager personnalisé pour CustomUser
Permet la création d'utilisateurs avec email comme identifiant principal
"""
from django.contrib.auth.base_user import BaseUserManager


class CustomUserManager(BaseUserManager):
    """
    Manager personnalisé qui utilise l'email comme identifiant unique
    au lieu du username Django par défaut.
    """

    def create_user(self, email, password=None, **extra_fields):
        """
        Crée et sauvegarde un utilisateur normal avec email + mot de passe.
        """
        if not email:
            raise ValueError("L'adresse email est obligatoire.")
        
        # Normalise l'email (lowercase du domaine)
        email = self.normalize_email(email)
        
        # Crée l'instance utilisateur
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Crée et sauvegarde un superutilisateur (admin Django).
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError("Le superutilisateur doit avoir is_staff=True.")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Le superutilisateur doit avoir is_superuser=True.")

        return self.create_user(email, password, **extra_fields)