"""
IvoirPass V2 — Administration du dashboard et wallet
"""
from .models import OrganizerWallet, WalletTransaction, WithdrawalRequest, AuditLog, ReversalOTP, Dispute
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import OrganizerWallet, WalletTransaction, WithdrawalRequest


class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    extra = 0
    readonly_fields = (
        'type', 'amount', 'balance_after',
        'description', 'reference', 'created_at'
    )
    can_delete = False
    max_num = 0


@admin.register(OrganizerWallet)
class OrganizerWalletAdmin(admin.ModelAdmin):
    list_display = (
        'organizer', 'balance_available',
        'balance_pending', 'balance_withdrawn',
        'preferred_payout_method', 'payout_phone'
    )
    search_fields = ('organizer__email', 'organizer__first_name', 'payout_phone')
    readonly_fields = ('balance_withdrawn', 'created_at', 'updated_at')
    inlines = [WalletTransactionInline]


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'get_organizer', 'amount',
        'payout_method', 'payout_phone',
        'status_badge', 'created_at'
    )
    list_filter  = ('status', 'payout_method')
    search_fields = (
        'reference',
        'wallet__organizer__email',
        'payout_phone'
    )
    readonly_fields = (
        'reference', 'amount_net',
        'created_at', 'processed_at'
    )
    actions = ['approve_requests', 'process_requests', 'reject_requests']

    def get_organizer(self, obj):
        return obj.wallet.organizer.get_full_name()
    get_organizer.short_description = "Organisateur"

    def status_badge(self, obj):
        colors = {
            'pending':   '#F47920',
            'approved':  '#1B7A3E',
            'processed': '#0dcaf0',
            'rejected':  '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;'
            'border-radius:20px;font-size:0.78rem;font-weight:700;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Statut"

    @admin.action(description="✅ Approuver les demandes sélectionnées")
    def approve_requests(self, request, queryset):
        count = 0
        for wr in queryset.filter(status=WithdrawalRequest.Status.PENDING):
            wr.approve(admin_user=request.user, note="Approuvé via admin")
            count += 1
        self.message_user(request, f"{count} demande(s) approuvée(s).")

    @admin.action(description="💸 Marquer comme traitées (virement effectué)")
    def process_requests(self, request, queryset):
        count = 0
        for wr in queryset.filter(
            status__in=[
                WithdrawalRequest.Status.PENDING,
                WithdrawalRequest.Status.APPROVED,
            ]
        ):
            wr.mark_processed(
                admin_user=request.user,
                note="Virement effectué via admin"
            )
            count += 1
        self.message_user(request, f"{count} reversement(s) traité(s).")

    @admin.action(description="❌ Rejeter les demandes sélectionnées")
    def reject_requests(self, request, queryset):
        count = 0
        for wr in queryset.filter(status=WithdrawalRequest.Status.PENDING):
            wr.reject(admin_user=request.user, note="Rejeté via admin")
            count += 1
        self.message_user(request, f"{count} demande(s) rejetée(s).")
@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ('reference', 'type', 'subject', 'reported_by', 'status_badge', 'created_at')
    list_filter = ('status', 'type')
    search_fields = ('reference', 'subject', 'reported_by__email', 'order_number')
    readonly_fields = ('reference', 'created_at', 'updated_at', 'resolved_at')

    def status_badge(self, obj):
        colors = {'open': '#F47920', 'investigating': '#0dcaf0', 'resolved': '#1B7A3E', 'closed': '#6c757d', 'rejected': '#dc3545'}
        color = colors.get(obj.status, '#6c757d')
        from django.utils.html import format_html
        return format_html('<span style="background:{};color:white;padding:3px 10px;border-radius:20px;font-size:0.78rem;">{}</span>', color, obj.get_status_display())
    status_badge.short_description = "Statut"

    actions = ['mark_investigating', 'mark_resolved', 'mark_closed']

    @admin.action(description="🔍 En cours d'investigation")
    def mark_investigating(self, request, queryset):
        queryset.filter(status=Dispute.Status.OPEN).update(status=Dispute.Status.INVESTIGATING)
        self.message_user(request, "Litiges passés en investigation.")

    @admin.action(description="✅ Marquer comme résolus")
    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.exclude(status=Dispute.Status.CLOSED).update(
            status=Dispute.Status.RESOLVED,
            resolved_by=request.user,
            resolved_at=timezone.now()
        )
        self.message_user(request, "Litiges résolus.")

    @admin.action(description="🔒 Fermer")
    def mark_closed(self, request, queryset):
        queryset.update(status=Dispute.Status.CLOSED)
        self.message_user(request, "Litiges fermés.")
