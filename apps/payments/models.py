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

    # Liaison commande — l'une des deux FK est renseignée, jamais les deux
    # (contrainte en base ci-dessous). "order" pour les comptes (flux
    # historique), "guest_order" pour les achats sans compte (flux actuel).
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
            models.Index(fields=['status']),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(order__isnull=False, guest_order__isnull=True) |
                    Q(order__isnull=True, guest_order__isnull=False)
                ),
                name='payment_exactly_one_of_order_or_guest_order',
            ),
        ]

    def __str__(self):
        ref = self.order.order_number if self.order_id else self.guest_order.order_number
        return f"Paiement {ref} — {self.amount} FCFA ({self.get_status_display()})"