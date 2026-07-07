"""
IvoirPass V2 — Modèle utilisateur personnalisé

Remplace le User Django par défaut.
Identifiant principal : email (pas username)
"""
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from .managers import CustomUserManager


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Modèle utilisateur IvoirPass.
    
    Rôles possibles :
    - participant   : Acheteur de tickets et produits culturels
    - organizer     : Organisateur d'événements / vendeur culturel
    - scanner       : Agent de contrôle d'accès (scan QR)
    - admin         : Administrateur de la plateforme
    """

    # ============================================
    # CHOIX DE RÔLES
    # ============================================
    class Role(models.TextChoices):
        PARTICIPANT = 'participant', _('Participant')
        ORGANIZER   = 'organizer',   _('Organisateur')
        SCANNER     = 'scanner',     _('Agent Scanner')
        ADMIN       = 'admin',       _('Administrateur')

    # ============================================
    # INFORMATIONS DE BASE
    # ============================================
    email = models.EmailField(
        _('adresse email'),
        unique=True,
        help_text="Identifiant principal de connexion"
    )
    first_name = models.CharField(
        _('prénom'),
        max_length=100,
        blank=True
    )
    last_name = models.CharField(
        _('nom de famille'),
        max_length=100,
        blank=True
    )
    phone_number = models.CharField(
        _('numéro de téléphone'),
        max_length=20,
        blank=True,
        null=True,
        help_text="Format international : +225 07 XX XX XX XX"
    )

    # ============================================
    # RÔLE ET STATUT
    # ============================================
    role = models.CharField(
        _('rôle'),
        max_length=20,
        choices=Role.choices,
        default=Role.PARTICIPANT,
    )
    is_active = models.BooleanField(
        _('actif'),
        default=True,
        help_text="Désactiver pour bannir un utilisateur sans supprimer son compte."
    )
    is_staff = models.BooleanField(
        _('accès admin'),
        default=False,
    )

    # ============================================
    # PROFIL
    # ============================================
    avatar = models.ImageField(
        _('photo de profil'),
        upload_to='avatars/%Y/%m/',
        blank=True,
        null=True,
    )
    bio = models.TextField(
        _('biographie'),
        blank=True,
        help_text="Utilisé pour les profils organisateurs"
    )

    # ============================================
    # VÉRIFICATION ORGANISATEUR (KYC)
    # ============================================
    is_organizer_verified = models.BooleanField(
        _('organisateur vérifié'),
        default=False,
        help_text="True quand l'admin a validé les documents KYC de l'organisateur"
    )
    organization_name = models.CharField(
        _('nom de l\'organisation'),
        max_length=200,
        blank=True,
        help_text="Nom de l'entreprise ou structure organisatrice"
    )
    organization_description = models.TextField(
        _('description de l\'organisation'),
        blank=True,
    )
    organization_logo = models.ImageField(
        _('logo de l\'organisation'),
        upload_to='logos/%Y/%m/',
        blank=True,
        null=True,
    )
    organization_website = models.URLField(
        _('site web'),
        blank=True,
    )

        # ============================================
    # KYC — DOCUMENTS
    # ============================================
    kyc_identity_doc = models.FileField(
        _('pièce d\'identité'),
        upload_to='kyc/identity/%Y/%m/',
        null=True, blank=True,
        help_text="Carte d'identité, passeport ou carte consulaire"
    )
    kyc_proof_of_address = models.FileField(
        _('justificatif de domicile'),
        upload_to='kyc/address/%Y/%m/',
        null=True, blank=True,
        help_text="Facture électricité, eau, ou attestation de domicile"
    )
    kyc_business_doc = models.FileField(
        _('document professionnel'),
        upload_to='kyc/business/%Y/%m/',
        null=True, blank=True,
        help_text="RCCM, attestation fiscale, ou déclaration d'activité"
    )
    kyc_submitted_at = models.DateTimeField(
        _('KYC soumis le'),
        null=True, blank=True
    )
    kyc_verified_at = models.DateTimeField(
        _('KYC vérifié le'),
        null=True, blank=True
    )
    kyc_verified_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='kyc_verified_users',
        verbose_name=_('KYC vérifié par')
    )
    kyc_notes = models.TextField(
        _('notes KYC'),
        blank=True,
        help_text="Notes internes de l'admin sur la vérification KYC"
    )

    # ============================================
    # PRÉFÉRENCES ET LOCALISATION
    # ============================================
    city = models.CharField(
        _('ville'),
        max_length=100,
        blank=True,
        default='Abidjan',
    )
    LANGUAGE_CHOICES = [
        ('fr', 'Français'),
        ('en', 'English'),
    ]
    preferred_language = models.CharField(
        _('langue préférée'),
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default='fr',
    )

    # ============================================
    # NOTIFICATIONS (préférences)
    # ============================================
    notify_email = models.BooleanField(
        _('notifications email'),
        default=True,
    )
    notify_sms = models.BooleanField(
        _('notifications SMS'),
        default=False,
    )
    notify_push = models.BooleanField(
        _('notifications push'),
        default=True,
    )

    # ============================================
    # DATES
    # ============================================
    date_joined = models.DateTimeField(
        _('date d\'inscription'),
        default=timezone.now,
    )
    last_login = models.DateTimeField(
        _('dernière connexion'),
        blank=True,
        null=True,
    )
    updated_at = models.DateTimeField(
        _('mis à jour le'),
        auto_now=True,
    )

    # ============================================
    # CONFIGURATION DU MANAGER
    # ============================================
    objects = CustomUserManager()

    # L'email remplace le username comme identifiant
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # Aucun autre champ requis pour createsuperuser

    class Meta:
        verbose_name = _('utilisateur')
        verbose_name_plural = _('utilisateurs')
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role']),
            models.Index(fields=['phone_number']),
        ]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    # ============================================
    # MÉTHODES UTILITAIRES
    # ============================================
    def get_full_name(self):
        """Retourne prénom + nom, ou email si non renseigné."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.email

    def get_short_name(self):
        """Retourne le prénom."""
        return self.first_name or self.email.split('@')[0]

    @property
    def is_participant(self):
        return self.role == self.Role.PARTICIPANT

    @property
    def is_organizer(self):
        return self.role == self.Role.ORGANIZER

    @property
    def is_scanner_agent(self):
        return self.role == self.Role.SCANNER

    @property
    def is_platform_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def display_name(self):
        """Nom d'affichage public : prénom ou nom d'organisation."""
        if self.is_organizer and self.organization_name:
            return self.organization_name
        return self.get_short_name()


class UserAddress(models.Model):
    """
    Adresses de livraison des utilisateurs.
    Un utilisateur peut avoir plusieurs adresses.
    Utilisé pour la livraison de livres et albums physiques.
    """
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='addresses',
        verbose_name=_('utilisateur'),
    )
    label = models.CharField(
        _('libellé'),
        max_length=100,
        help_text="Ex: Domicile, Bureau, Maison familiale"
    )
    full_name = models.CharField(
        _('nom complet du destinataire'),
        max_length=200,
    )
    phone = models.CharField(
        _('téléphone'),
        max_length=20,
    )
    address_line1 = models.CharField(
        _('adresse ligne 1'),
        max_length=255,
        help_text="Numéro et nom de rue, quartier"
    )
    address_line2 = models.CharField(
        _('adresse ligne 2'),
        max_length=255,
        blank=True,
        help_text="Complément d'adresse, bâtiment, appartement"
    )
    latitude = models.DecimalField(
        _('latitude'),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Coordonnée GPS automatique"
    )
    longitude = models.DecimalField(
        _('longitude'),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Coordonnée GPS automatique"
    )
    city = models.CharField(
        _('ville'),
        max_length=100,
        default='Abidjan',
    )
    ZONE_CHOICES = [
        ('abidjan', 'Abidjan'),
        ('grandes_villes', 'Grandes villes (Bouaké, Daloa, Yamoussoukro...)'),
        ('interieur', 'Intérieur du pays'),
    ]
    zone = models.CharField(
        _('zone de livraison'),
        max_length=20,
        choices=ZONE_CHOICES,
        default='abidjan',
    )
    is_default = models.BooleanField(
        _('adresse par défaut'),
        default=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('adresse')
        verbose_name_plural = _('adresses')
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f"{self.label} — {self.full_name} ({self.city})"

    def save(self, *args, **kwargs):
        """
        Si cette adresse est définie comme défaut,
        retire le statut par défaut des autres adresses.
        """
        if self.is_default:
            UserAddress.objects.filter(
                user=self.user,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def shipping_cost(self):
        """Calcule les frais de livraison selon la zone."""
        costs = {
            'abidjan': 1200,
            'grandes_villes': 2500,
            'interieur': 4000,
        }
        return costs.get(self.zone, 1200)