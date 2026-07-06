"""
IvoirPass V2 — Administration des paiements
"""
from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'order', 'amount', 'provider',
        'status', 'paydunya_token', 'created_at'
    )
    list_filter  = ('status', 'provider', 'currency')
    search_fields = (
        'order__order_number',
        'paydunya_token',
        'order__buyer__email'
    )
    readonly_fields = (
        'paydunya_token', 'paydunya_invoice_token',
        'raw_response', 'created_at', 'updated_at', 'completed_at'
    )
    fieldsets = (
        ('Commande', {
            'fields': ('order', 'amount', 'currency')
        }),
        ('PayDunya', {
            'fields': (
                'paydunya_token',
                'paydunya_invoice_token',
                'provider', 'status'
            )
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
        ('Données brutes', {
            'fields': ('raw_response',),
            'classes': ('collapse',)
        }),
    )