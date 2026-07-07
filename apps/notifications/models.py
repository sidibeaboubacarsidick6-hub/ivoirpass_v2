from django.db import models

# Create your models here.
"""
IvoirPass V2 — Modèles de notification
"""
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class AdminNotification(models.Model):
    """
    Notification pour les administrateurs de la plateforme.
    """
    class Type(models.TextChoices):
        NEW_EVENT    = 'new_event',    _('Nouvel événement')
        NEW_PRODUCT  = 'new_product',  _('Nouveau produit')
        WITHDRAWAL   = 'withdrawal',   _('Demande de reversement')
        FRAUD_ALERT  = 'fraud_alert',  _('Alerte fraude')

    type = models.CharField(_('type'), max_length=20, choices=Type.choices)
    title = models.CharField(_('titre'), max_length=200)
    message = models.TextField(_('message'))
    reference = models.CharField(_('référence'), max_length=200, blank=True)
    is_read = models.BooleanField(_('lu'), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('notification admin')
        verbose_name_plural = _('notifications admin')
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_type_display()}] {self.title}"
