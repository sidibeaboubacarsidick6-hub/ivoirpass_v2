"""
IvoirPass V2 — Administration des tickets
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import Order, OrderItem, Ticket


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('subtotal',)
    fields = ('ticket_type', 'quantity', 'unit_price', 'subtotal')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'buyer', 'status',
        'total', 'payment_method', 'created_at'
    )
    list_filter  = ('status', 'payment_method')
    search_fields = ('order_number', 'buyer__email', 'payment_reference')
    readonly_fields = (
        'order_number', 'uuid',
        'created_at', 'updated_at', 'paid_at'
    )
    inlines = [OrderItemInline]

    actions = ['mark_paid']

    @admin.action(description="✅ Marquer comme payées")
    def mark_paid(self, request, queryset):
        for order in queryset.filter(status=Order.Status.PENDING):
            order.mark_as_paid(payment_method='manual')
        self.message_user(request, "Commandes marquées comme payées.")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_number', 'get_event', 'get_buyer',
        'status', 'qr_preview', 'scanned_at'
    )
    list_filter  = ('status',)
    search_fields = ('ticket_number', 'order_item__order__buyer__email')
    readonly_fields = (
        'uuid', 'ticket_number', 'qr_code_data',
        'qr_preview', 'created_at', 'scanned_at'
    )

    def get_event(self, obj):
        return obj.event.title
    get_event.short_description = "Événement"

    def get_buyer(self, obj):
        return obj.buyer.email
    get_buyer.short_description = "Acheteur"

    def qr_preview(self, obj):
        if obj.qr_code_image:
            return format_html(
                '<img src="{}" width="80" height="80" />',
                obj.qr_code_image.url
            )
        return "—"
    qr_preview.short_description = "QR Code"