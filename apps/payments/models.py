"""
IvoirPass V2 — Modèle de transaction de paiement
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.db.models import Q


class Payment(models.Model):
    """
    Enregistre chaque tentative de paiement PayDunya.
    Conserve l'historique complet pour la comptabilité et les litiges.
    """

    class Status(models.TextChoices):
        PENDING   = 'pending',   _('En attente')
        COMPLETED = 'completed', _('Complété')
        FAILED    = 'failed',    _('Échoué')
        CANCELLED = 'cancelled', _('Annulé')
        REFUNDED  = 'refunded',  _('Remboursé')

    class Provider(models.TextChoices):
        PAYDUNYA = 'paydunya', 'PayDunya'
        WAVE     = 'wave',     'Wave'
        ORANGE   = 'orange',   'Orange Money'
        MTN      = 'mtn',      'MTN MoMo'
        MOOV     = 'moov',     'Moov Money'
        DJAMO    = 'djamo',    'Djamo'
        CARD     = 'card',     'Carte Bancaire'

    # Liaison commande — exactement une seule des quatre FK est renseignée
    # (contrainte en base ci-dessous). "order"/"guest_order" pour la
    # billetterie, "product_order"/"guest_product_order" pour la boutique.
    # La boutique ne vend aujourd'hui qu'en achat invité (guest_product_order) —
    # product_order existe pour rester cohérent avec order/guest_order et pour
    # le jour où le tunnel "avec compte" boutique serait réactivé.
    order = models.ForeignKey(
        'tickets.Order',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('commande'),
        null=True, blank=True,
    )
    guest_order = models.ForeignKey(
        'tickets.GuestOrder',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('commande invité'),
        null=True, blank=True,
    )
    product_order = models.ForeignKey(
        'store.ProductOrder',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('commande boutique'),
        null=True, blank=True,
    )
    guest_product_order = models.ForeignKey(
        'store.GuestProductOrder',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('commande boutique invité'),
        null=True, blank=True,
    )

    # Identifiants PayDunya
    paydunya_token = models.CharField(
        _('token PayDunya'),
        max_length=200,
        blank=True,
        help_text="Token unique de la transaction PayDunya"
    )
    paydunya_invoice_token = models.CharField(
        _('token facture'),
        max_length=200,
        blank=True
    )

    # Détails du paiement
    provider = models.CharField(
        _('opérateur'),
        max_length=20,
        choices=Provider.choices,
        default=Provider.PAYDUNYA
    )
    amount = models.DecimalField(
        _('montant'),
        max_digits=12,
        decimal_places=0
    )
    currency = models.CharField(
        _('devise'),
        max_length=5,
        default='XOF'
    )
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Données brutes de la réponse PayDunya (pour debug/audit)
    raw_response = models.JSONField(
        _('réponse brute'),
        null=True, blank=True
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('paiement')
        verbose_name_plural = _('paiements')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['paydunya_token']),
            models.Index(fields=['order', 'status']),
            models.Index(fields=['guest_order', 'status']),
            models.Index(fields=['product_order', 'status']),
            models.Index(fields=['guest_product_order', 'status']),
            models.Index(fields=['status']),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(order__isnull=False, guest_order__isnull=True, product_order__isnull=True, guest_product_order__isnull=True) |
                    Q(order__isnull=True, guest_order__isnull=False, product_order__isnull=True, guest_product_order__isnull=True) |
                    Q(order__isnull=True, guest_order__isnull=True, product_order__isnull=False, guest_product_order__isnull=True) |
                    Q(order__isnull=True, guest_order__isnull=True, product_order__isnull=True, guest_product_order__isnull=False)
                ),
                name='payment_exactly_one_order_type',
            ),
        ]

    def __str__(self):
        order = self.order or self.guest_order or self.product_order or self.guest_product_order
        ref = order.order_number if order else '?'
        return f"Paiement {ref} — {self.amount} FCFA ({self.get_status_display()})"