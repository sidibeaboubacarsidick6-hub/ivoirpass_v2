"""
IvoirPass V2 — Administration du Scanner
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import ScanSession, ScanLog


class ScanLogInline(admin.TabularInline):
    model = ScanLog
    extra = 0
    readonly_fields = (
        'ticket', 'result', 'qr_data_received', 'scanned_at'
    )
    can_delete = False
    max_num = 0


@admin.register(ScanSession)
class ScanSessionAdmin(admin.ModelAdmin):
    list_display = (
        'agent', 'event', 'started_at',
        'total_scanned', 'total_valid',
        'total_rejected', 'success_rate'
    )
    list_filter  = ('event', 'agent')
    readonly_fields = (
        'started_at', 'ended_at',
        'total_scanned', 'total_valid', 'total_rejected'
    )
    inlines = [ScanLogInline]

    def success_rate(self, obj):
        if obj.total_scanned == 0:
            return '—'
        rate = round(obj.total_valid / obj.total_scanned * 100, 1)
        color = '#1B7A3E' if rate > 80 else '#F47920'
        return format_html(
            '<span style="color:{};font-weight:700;">{} %</span>',
            color, rate
        )
    success_rate.short_description = "Taux de succès"


@admin.register(ScanLog)
class ScanLogAdmin(admin.ModelAdmin):
    list_display  = (
        'session', 'ticket', 'result_badge', 'scanned_at'
    )
    list_filter   = ('result', 'session__event')
    search_fields = (
        'qr_data_received',
        'ticket__ticket_number',
        'session__agent__email'
    )
    readonly_fields = (
        'session', 'ticket', 'qr_data_received',
        'result', 'scanned_at'
    )

    def result_badge(self, obj):
        colors = {
            'valid':        '#1B7A3E',
            'already_used': '#dc3545',
            'invalid_qr':   '#6c757d',
            'wrong_event':  '#F47920',
            'ticket_void':  '#6c757d',
            'not_found':    '#6c757d',
        }
        color = colors.get(obj.result, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;'
            'border-radius:12px;font-size:0.78rem;">{}</span>',
            color, obj.get_result_display()
        )
    result_badge.short_description = "Résultat"