"""
IvoirPass V2 — Administration des paiements
"""
from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'commande', 'amount', 'provider',
        'status', 'paydunya_token', 'created_at'
    )
    list_filter  = ('status', 'provider', 'currency')
    search_fields = (
        'order__order_number',
        'guest_order__order_number',
        'product_order__order_number',
        'guest_product_order__order_number',
        'paydunya_token',
        'order__buyer__email',
        'guest_order__email',
        'product_order__buyer__email',
        'guest_product_order__email',
    )
    # 'status' et 'amount' sont en lecture seule : une transaction
    # financière ne doit jamais être modifiée silencieusement depuis
    # l'admin. Toute correction nécessaire doit passer par une nouvelle
    # écriture tracée (remboursement, ajustement...) plutôt qu'une édition
    # directe qui ne laisserait aucune trace dans le journal d'audit.
    readonly_fields = (
        'paydunya_token', 'paydunya_invoice_token', 'status', 'amount',
        'raw_response', 'created_at', 'updated_at', 'completed_at'
    )

    def commande(self, obj):
        # Une seule des quatre FK est renseignée (contrainte en base) —
        # billetterie (order/guest_order) ou boutique
        # (product_order/guest_product_order, voir extension du modèle
        # Payment pour la réconciliation/back-office boutique).
        order = obj.order or obj.guest_order or obj.product_order or obj.guest_product_order
        return order.order_number if order else '—'
    commande.short_description = 'Commande'

    fieldsets = (
        ('Commande', {
            'fields': (
                'order', 'guest_order', 'product_order', 'guest_product_order',
                'amount', 'currency',
            )
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