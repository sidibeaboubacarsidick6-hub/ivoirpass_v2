"""
IvoirPass V2 — Admin du chatbot.
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import ChatbotLog


@admin.register(ChatbotLog)
class ChatbotLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'short_question', 'sections_found',
        'failure_badge', 'error_type', 'escalated_link',
    )
    list_filter = ('was_failure', 'error_type', 'created_at')
    search_fields = ('question', 'answer', 'session_key')
    readonly_fields = (
        'question', 'answer', 'session_key', 'sections_found',
        'was_failure', 'error_type', 'escalated_to_dispute', 'created_at',
    )
    date_hierarchy = 'created_at'
    list_per_page = 50

    fieldsets = (
        ('Interaction', {
            'fields': ('question', 'answer', 'sections_found', 'was_failure', 'error_type'),
        }),
        ('Contexte', {
            'fields': ('session_key', 'escalated_to_dispute', 'created_at'),
        }),
    )

    def short_question(self, obj):
        return obj.question[:80]
    short_question.short_description = 'Question'

    def failure_badge(self, obj):
        if obj.was_failure:
            return format_html(
                '<span style="background:#dc3545;color:white;'
                'padding:2px 8px;border-radius:10px;font-size:0.75rem;">'
                'Échec</span>'
            )
        return format_html(
            '<span style="background:#1B7A3E;color:white;'
            'padding:2px 8px;border-radius:10px;font-size:0.75rem;">'
            'OK</span>'
        )
    failure_badge.short_description = 'Statut'

    def escalated_link(self, obj):
        if obj.escalated_to_dispute:
            return format_html(
                '<a href="/admin/dashboard/dispute/{}/change/">{}</a>',
                obj.escalated_to_dispute.pk,
                obj.escalated_to_dispute.reference,
            )
        return '—'
    escalated_link.short_description = 'Litige'

    def has_add_permission(self, request):
        return False  # Les logs sont immuables

    def has_change_permission(self, request, obj=None):
        return False  # Lecture seule (consultation seulement)