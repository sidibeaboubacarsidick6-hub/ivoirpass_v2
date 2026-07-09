"""
IvoirPass V2 — Modèles du Dashboard Organisateur
Wallet de reversement et transactions
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class OrganizerWallet(models.Model):
    """
    Portefeuille électronique de l'organisateur.
    Crédité automatiquement après chaque vente confirmée.
    """
    organizer = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet',
        verbose_name=_('organisateur'),
        limit_choices_to={'role': 'organizer'}
    )

    # Soldes
    balance_available = models.DecimalField(
        _('solde disponible'),
        max_digits=14, decimal_places=0,
        default=0,
        help_text="Montant disponible pour reversement"
    )
    balance_pending = models.DecimalField(
        _('solde en attente'),
        max_digits=14, decimal_places=0,
        default=0,
        help_text="Montant en attente de confirmation (délai sécurité 48h)"
    )
    balance_withdrawn = models.DecimalField(
        _('total reversé'),
        max_digits=14, decimal_places=0,
        default=0,
        help_text="Total cumulé des reversements effectués"
    )

    # Informations de reversement
    MOBILE_MONEY_CHOICES = [
        ('wave',         'Wave CI'),
        ('orange_money', 'Orange Money CI'),
        ('mtn_momo',     'MTN MoMo CI'),
        ('moov',         'Moov Money'),
    ]
    preferred_payout_method = models.CharField(
        _('méthode de reversement préférée'),
        max_length=20,
        choices=MOBILE_MONEY_CHOICES,
        default='wave'
    )
    payout_phone = models.CharField(
        _('numéro Mobile Money'),
        max_length=20,
        blank=True,
        help_text="Numéro pour recevoir les reversements"
    )
    payout_name = models.CharField(
        _('nom du bénéficiaire'),
        max_length=200,
        blank=True,
        help_text="Nom enregistré sur le compte Mobile Money"
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('wallet organisateur')
        verbose_name_plural = _('wallets organisateurs')

    def __str__(self):
        return (
            f"Wallet {self.organizer.get_full_name()} — "
            f"{self.balance_available} FCFA disponible"
        )

    @property
    def total_balance(self):
        return self.balance_available + self.balance_pending

    def credit(self, amount, description='', reference=''):
        """Crédite le wallet après une vente confirmée."""
        self.balance_available += amount
        self.save(update_fields=['balance_available', 'updated_at'])
        WalletTransaction.objects.create(
            wallet      = self,
            type        = WalletTransaction.Type.CREDIT,
            amount      = amount,
            balance_after = self.balance_available,
            description = description,
            reference   = reference,
        )

    def debit(self, amount, description='', reference=''):
        """Débite le wallet lors d'un reversement."""
        if amount > self.balance_available:
            raise ValueError("Solde insuffisant pour ce reversement.")
        self.balance_available -= amount
        self.balance_withdrawn += amount
        self.balance_pending = max(0, self.balance_pending - amount)
        self.save(update_fields=[
            'balance_available', 'balance_withdrawn', 'balance_pending', 'updated_at'
        ])
        WalletTransaction.objects.create(
            wallet        = self,
            type          = WalletTransaction.Type.DEBIT,
            amount        = amount,
            balance_after = self.balance_available,
            description   = description,
            reference     = reference,
        )


class WalletTransaction(models.Model):
    """
    Historique de toutes les transactions du wallet.
    Traçabilité complète pour la comptabilité.
    """
    class Type(models.TextChoices):
        CREDIT     = 'credit',     _('Crédit (vente)')
        DEBIT      = 'debit',      _('Débit (reversement)')
        ADJUSTMENT = 'adjustment', _('Ajustement manuel')
        REFUND     = 'refund',     _('Remboursement')

    wallet = models.ForeignKey(
        OrganizerWallet,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name=_('wallet')
    )
    type = models.CharField(
        _('type'),
        max_length=20,
        choices=Type.choices
    )
    amount = models.DecimalField(
        _('montant'),
        max_digits=14,
        decimal_places=0
    )
    balance_after = models.DecimalField(
        _('solde après'),
        max_digits=14,
        decimal_places=0
    )
    description = models.CharField(
        _('description'),
        max_length=500,
        blank=True
    )
    reference = models.CharField(
        _('référence'),
        max_length=200,
        blank=True,
        help_text="Numéro de commande ou de reversement associé"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('transaction wallet')
        verbose_name_plural = _('transactions wallet')
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"{self.get_type_display()} — "
            f"{self.amount} FCFA — "
            f"{self.created_at.strftime('%d/%m/%Y')}"
        )


class WithdrawalRequest(models.Model):
    """
    Demande de reversement d'un organisateur.
    Validée manuellement par l'admin IvoirPass.
    """
    class Status(models.TextChoices):
        PENDING   = 'pending',   _('En attente')
        APPROVED  = 'approved',  _('Approuvée')
        PROCESSED = 'processed', _('Traitée')
        REJECTED  = 'rejected',  _('Rejetée')

    # Numéro unique
    reference = models.CharField(
        _('référence'),
        max_length=30,
        unique=True,
        blank=True
    )

    wallet = models.ForeignKey(
        OrganizerWallet,
        on_delete=models.CASCADE,
        related_name='withdrawal_requests',
        verbose_name=_('wallet')
    )

    # Montant
    amount = models.DecimalField(
        _('montant demandé'),
        max_digits=14,
        decimal_places=0
    )
    fee = models.DecimalField(
        _('frais de traitement'),
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Frais éventuels déduits du reversement"
    )
    amount_net = models.DecimalField(
        _('montant net reversé'),
        max_digits=14,
        decimal_places=0,
        default=0
    )

    # Coordonnées de paiement
    MOBILE_MONEY_CHOICES = [
        ('wave',         'Wave CI'),
        ('orange_money', 'Orange Money CI'),
        ('mtn_momo',     'MTN MoMo CI'),
        ('moov',         'Moov Money'),
    ]
    payout_method = models.CharField(
        _('méthode'),
        max_length=20,
        choices=MOBILE_MONEY_CHOICES
    )
    payout_phone = models.CharField(
        _('numéro Mobile Money'),
        max_length=20
    )
    payout_name = models.CharField(
        _('nom bénéficiaire'),
        max_length=200
    )

    # Statut et traitement
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    admin_note = models.TextField(
        _('note admin'),
        blank=True,
        help_text="Commentaire de l'administrateur"
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='processed_withdrawals',
        verbose_name=_('traité par')
    )

    # Dates
    created_at   = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('demande de reversement')
        verbose_name_plural = _('demandes de reversement')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', 'status']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return (
            f"Reversement {self.reference} — "
            f"{self.amount} FCFA — {self.get_status_display()}"
        )

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = self._generate_reference()
        if not self.amount_net:
            self.amount_net = self.amount - self.fee
        super().save(*args, **kwargs)

    def _generate_reference(self):
        import random, string
        suffix = ''.join(random.choices(string.digits, k=8))
        return f"REV-{suffix}"

    def approve(self, admin_user, note=''):
        """Approuve la demande — déclenche le débit du wallet."""
        self.status      = self.Status.APPROVED
        self.admin_note  = note
        self.processed_by = admin_user
        self.save()

    def mark_processed(self, admin_user, note=''):
        """Marque comme traitée après virement effectué."""
        self.status       = self.Status.PROCESSED
        self.admin_note   = note
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.save()

        # Mettre à jour balance_pending
        self.wallet.balance_pending = max(0, self.wallet.balance_pending - self.amount)
        self.wallet.save(update_fields=['balance_pending'])

        # Débiter le wallet
        self.wallet.debit(
            amount=self.amount,
            description=f"Reversement {self.reference}",
            reference=self.reference,
        )

        # Notification admin
        from apps.notifications.models import AdminNotification
        AdminNotification.objects.create(
            type='fraud_alert',
            title='Reversement traite',
            message=(
                f"Reversement {self.reference} de {self.amount} FCFA "
                f"traite pour {self.wallet.organizer.get_full_name()}."
            ),
            reference=self.reference,
        )

        # Email à l'organisateur
        from django.core.mail import send_mail
        send_mail(
            '[IvoirPass] Reversement effectue',
            f"Bonjour {self.wallet.organizer.get_full_name()},\n\n"
            f"Votre reversement de {self.amount} FCFA a ete traite.\n"
            f"Reference : {self.reference}\n\n"
            f"L'equipe IvoirPass",
            None,
            [self.wallet.organizer.email],
            fail_silently=False,
        )
    def reject(self, admin_user, note=''):
        """Rejette la demande — restitue le solde bloqué."""
        self.status       = self.Status.REJECTED
        self.admin_note   = note
        self.processed_by = admin_user
        self.processed_at = timezone.now()
        self.save()
class ReversalOTP(models.Model):
    """
    Code OTP pour valider une demande de reversement.
    Envoyé par email ET SMS. Valable 10 minutes.
    """
    withdrawal = models.OneToOneField(
        WithdrawalRequest,
        on_delete=models.CASCADE,
        related_name='otp',
        verbose_name=_('demande de reversement')
    )
    code = models.CharField(_('code OTP'), max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('OTP reversement')
        verbose_name_plural = _('OTP reversements')

    def __str__(self):
        return f"OTP {self.code} — {self.withdrawal.reference}"

    @property
    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and timezone.now() < self.expires_at

    @classmethod
    def generate(cls, withdrawal):
        import random
        from django.utils import timezone
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        expires_at = timezone.now() + timezone.timedelta(minutes=10)
        return cls.objects.create(
            withdrawal=withdrawal,
            code=code,
            expires_at=expires_at
        )

class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'create', _('Création')
        UPDATE = 'update', _('Modification')
        DELETE = 'delete', _('Suppression')
        PUBLISH = 'publish', _('Publication')
        UNPUBLISH = 'unpublish', _('Dépublier')
        LOGIN = 'login', _('Connexion')
        LOGOUT = 'logout', _('Déconnexion')
        PAYOUT = 'payout', _('Reversement')
        EXPORT = 'export', _('Export données')
        SCAN = 'scan', _('Scan QR')
        OTHER = 'other', _('Autre')

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='audit_logs', verbose_name=_('utilisateur'))
    action = models.CharField(_('action'), max_length=20, choices=Action.choices)
    model_name = models.CharField(_('modèle'), max_length=100, blank=True)
    object_id = models.CharField(_('ID objet'), max_length=100, blank=True)
    description = models.TextField(_('description'))
    ip_address = models.GenericIPAddressField(_('adresse IP'), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('entrée d\'audit')
        verbose_name_plural = _('journal d\'audit')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'[{self.created_at:%d/%m/%Y %H:%M}] {self.user} — {self.get_action_display()}'



class Dispute(models.Model):
    """
    Gestion des litiges et réclamations.
    """
    class Type(models.TextChoices):
        REFUND      = 'refund',      _('Remboursement')
        NON_DELIVERY = 'non_delivery', _('Non-livraison')
        QR_ISSUE    = 'qr_issue',    _('Problème QR code')
        WRONG_ITEM  = 'wrong_item',  _('Mauvais produit')
        OTHER       = 'other',       _('Autre')

    class Status(models.TextChoices):
        OPEN       = 'open',        _('Ouvert')
        INVESTIGATING = 'investigating', _('En cours')
        RESOLVED   = 'resolved',    _('Résolu')
        CLOSED     = 'closed',      _('Fermé')
        REJECTED   = 'rejected',    _('Rejeté')

    reference = models.CharField(_('référence'), max_length=30, unique=True, blank=True)
    type = models.CharField(_('type'), max_length=20, choices=Type.choices)
    status = models.CharField(_('statut'), max_length=20, choices=Status.choices, default=Status.OPEN)

    # Plaignant
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='disputes',
        verbose_name=_('signalé par')
    )
    email = models.EmailField(_('email contact'), blank=True)
    phone = models.CharField(_('téléphone'), max_length=20, blank=True)

    # Éléments concernés
    order_number = models.CharField(_('numéro de commande'), max_length=30, blank=True)
    ticket_number = models.CharField(_('numéro de ticket'), max_length=30, blank=True)
    subject = models.CharField(_('sujet'), max_length=200)
    description = models.TextField(_('description'))

    # Résolution
    resolution = models.TextField(_('résolution'), blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='resolved_disputes',
        verbose_name=_('résolu par')
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('litige')
        verbose_name_plural = _('litiges')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['type']),
            models.Index(fields=['reference']),
        ]

    def __str__(self):
        return f"Litige {self.reference} — {self.get_type_display()}"

    def save(self, *args, **kwargs):
        if not self.reference:
            import random, string
            suffix = ''.join(random.choices(string.digits, k=8))
            self.reference = f"LIT-{suffix}"
        super().save(*args, **kwargs)

    def resolve(self, admin_user, resolution=''):
        from django.utils import timezone
        self.status = self.Status.RESOLVED
        self.resolution = resolution
        self.resolved_by = admin_user
        self.resolved_at = timezone.now()
        self.save()
