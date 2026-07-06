"""
IvoirPass V2 — Modèles du Scanner QR Code
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class ScanSession(models.Model):
    """
    Session de scan d'un agent pour un événement.
    Tracke l'activité de chaque agent à chaque événement.
    """
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scan_sessions',
        verbose_name=_('agent scanner')
    )
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='scan_sessions',
        verbose_name=_('événement')
    )
    started_at = models.DateTimeField(
        _('démarré le'),
        auto_now_add=True
    )
    ended_at = models.DateTimeField(
        _('terminé le'),
        null=True, blank=True
    )
    total_scanned = models.PositiveIntegerField(
        _('total scanné'),
        default=0
    )
    total_valid = models.PositiveIntegerField(
        _('total valides'),
        default=0
    )
    total_rejected = models.PositiveIntegerField(
        _('total rejetés'),
        default=0
    )

    class Meta:
        verbose_name = _('session de scan')
        verbose_name_plural = _('sessions de scan')
        ordering = ['-started_at']

    def __str__(self):
        return (
            f"Session {self.agent.get_full_name()} — "
            f"{self.event.title} — "
            f"{self.started_at.strftime('%d/%m/%Y %H:%M')}"
        )


class ScanLog(models.Model):
    """
    Enregistrement de chaque tentative de scan.
    """
    class Result(models.TextChoices):
        VALID           = 'valid',           _('Valide ✅')
        ALREADY_USED    = 'already_used',    _('Déjà utilisé ❌')
        INVALID_QR      = 'invalid_qr',      _('QR invalide ⛔')
        WRONG_EVENT     = 'wrong_event',     _('Mauvais événement ⚠️')
        TICKET_VOID     = 'ticket_void',     _('Ticket annulé 🚫')
        NOT_FOUND       = 'not_found',       _('Ticket introuvable 🔍')

    session = models.ForeignKey(
        ScanSession,
        on_delete=models.CASCADE,
        related_name='logs',
        verbose_name=_('session')
    )
    ticket = models.ForeignKey(
        'tickets.Ticket',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scan_logs',
        verbose_name=_('ticket')
    )
    qr_data_received = models.CharField(
        _('données QR reçues'),
        max_length=500,
        help_text="Données brutes scannées"
    )
    result = models.CharField(
        _('résultat'),
        max_length=20,
        choices=Result.choices
    )
    scanned_at = models.DateTimeField(
        _('scanné le'),
        auto_now_add=True
    )

    class Meta:
        verbose_name = _('log de scan')
        verbose_name_plural = _('logs de scan')
        ordering = ['-scanned_at']

    def __str__(self):
        return (
            f"Scan {self.get_result_display()} — "
            f"{self.scanned_at.strftime('%H:%M:%S')}"
        )