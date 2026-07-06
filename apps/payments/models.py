"""
IvoirPass V2 — Modèle de transaction de paiement
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


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

    # Liaison commande
    order = models.ForeignKey(
        'tickets.Order',
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('commande')
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
        ]

    def __str__(self):
        return (
            f"Paiement {self.order.order_number} — "
            f"{self.amount} FCFA ({self.get_status_display()})"
        )