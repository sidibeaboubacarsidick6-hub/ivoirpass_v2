"""
IvoirPass V2 — Modèles du chatbot.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _


class ChatbotLog(models.Model):
    """
    Journal des interactions avec le chatbot (ajout 2026-10-16).

    Chaque appel à ChatbotService.answer() crée une ligne — succès ou échec.
    Permet d'analyser les questions ratées et d'améliorer l'index RAG.
    """
    class ErrorType(models.TextChoices):
        NONE            = '',               _('Aucune')
        DISABLED        = 'disabled',       _('Chatbot désactivé')
        SESSION_LIMIT   = 'session_limit',  _('Limite de session atteinte')
        NO_SECTIONS     = 'no_sections',    _('Aucune section trouvée')
        MISTRAL_FAILED  = 'mistral_failed', _('Erreur Mistral')

    question = models.TextField(_('question'))
    answer = models.TextField(_('réponse'), blank=True)
    session_key = models.CharField(_('session'), max_length=100, db_index=True)
    sections_found = models.PositiveIntegerField(_('sections trouvées'), default=0)
    was_failure = models.BooleanField(_('échec'), default=False, db_index=True)
    error_type = models.CharField(
        _("type d'erreur"), max_length=30,
        choices=ErrorType.choices, blank=True, default='',
    )
    escalated_to_dispute = models.ForeignKey(
        'dashboard.Dispute',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='chatbot_logs',
        verbose_name=_('litige associé'),
    )
    created_at = models.DateTimeField(_('créé le'), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('log chatbot')
        verbose_name_plural = _('logs chatbot')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at', 'was_failure']),
        ]

    def __str__(self):
        status = "❌" if self.was_failure else "✓"
        return f"{status} {self.created_at:%d/%m %H:%M} — {self.question[:60]}"