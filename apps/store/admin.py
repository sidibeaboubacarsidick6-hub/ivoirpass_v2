"""
IvoirPass V2 — Administration de la boutique
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import ProductCategory, Product, ProductOrder, DownloadLink



@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'icon', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}


class DownloadLinkInline(admin.TabularInline):
    model  = DownloadLink
    extra  = 0
    readonly_fields = (
        'token', 'download_count',
        'expires_at', 'is_valid_display'
    )
    can_delete = False

    def is_valid_display(self, obj):
        if obj.is_valid:
            return format_html(
                '<span style="color:#1B7A3E; font-weight:700;">✅ Valide</span>'
            )
        return format_html(
            '<span style="color:#dc3545; font-weight:700;">❌ Expiré</span>'
        )
    is_valid_display.short_description = "Statut"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    actions = ['publish_products', 'archive_products', 'approve_and_publish', 'reject_to_draft']

    list_display = (
        'name', 'seller', 'category', 'product_type',
        'price', 'stock', 'sold_count', 'status', 'cover_preview'
    )
    list_filter  = ('status', 'product_type', 'category', 'is_featured')
    search_fields = ('name', 'author', 'seller__email')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = (
        'uuid', 'sold_count', 'created_at',
        'updated_at', 'published_at', 'cover_preview'
    )

    fieldsets = (
        ('Informations', {
            'fields': (
                'name', 'subtitle', 'slug', 'uuid',
                'description', 'short_description',
                'category', 'product_type', 'tags', 'seller'
            )
        }),
        ('Métadonnées', {
            'fields': (
                'author', 'publisher', 'year',
                'language', 'pages', 'duration', 'isbn'
            )
        }),
        ('Médias & Fichiers', {
            'fields': (
                'cover_image', 'cover_preview',
                'preview_file', 'digital_file'
            )
        }),
        ('Prix & Stock', {
            'fields': (
                'price', 'price_physical', 'price_digital',
                'stock', 'sold_count'
            )
        }),
        ('Téléchargement', {
            'fields': ('download_limit', 'download_expiry_hours')
        }),
        ('Publication', {
            'fields': (
                'status', 'is_featured',
                'published_at', 'created_at', 'updated_at'
            )
        }),
    )

    def cover_preview(self, obj):
        if obj.cover_image:
            return format_html(
                '<img src="{}" style="max-height:80px; border-radius:8px;" />',
                obj.cover_image.url
            )
        return "—"
    cover_preview.short_description = "Aperçu"

    actions = ['publish_products', 'archive_products']

    @admin.action(description="✅ Publier les produits sélectionnés")
    def publish_products(self, request, queryset):
        updated = queryset.filter(
            status=Product.Status.DRAFT
        ).update(status=Product.Status.PUBLISHED)
        self.message_user(request, f"{updated} produit(s) publié(s).")

    @admin.action(description="📦 Archiver les produits sélectionnés")
    def archive_products(self, request, queryset):
        updated = queryset.update(status=Product.Status.ARCHIVED)
        self.message_user(request, f"{updated} produit(s) archivé(s).")


@admin.register(ProductOrder)
class ProductOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'buyer', 'product',
        'quantity', 'total', 'status', 'created_at'
    )
    list_filter  = ('status', 'delivery_method', 'product__product_type')
    search_fields = (
        'order_number', 'buyer__email', 'product__name'
    )
    readonly_fields = (
        'order_number', 'uuid', 'subtotal',
        'created_at', 'updated_at', 'paid_at'
    )
    inlines = [DownloadLinkInline]

    actions = ['mark_paid', 'mark_shipped']

    @admin.action(description="✅ Marquer comme payées")
    def mark_paid(self, request, queryset):
        for order in queryset.filter(status=ProductOrder.Status.PENDING):
            order.mark_as_paid(payment_method='manual')
        self.message_user(request, "Commandes confirmées.")

    @admin.action(description="🚚 Marquer comme expédiées")
    def mark_shipped(self, request, queryset):
        from django.utils import timezone
        queryset.filter(
            status=ProductOrder.Status.PAID
        ).update(
            status=ProductOrder.Status.SHIPPED,
            shipped_at=timezone.now()
        )
        self.message_user(request, "Commandes marquées comme expédiées.")
    
    @admin.action(description="✅ Approuver et publier")
    def approve_and_publish(self, request, queryset):
        updated = queryset.filter(
        status=Product.Status.DRAFT
        ).update(status=Product.Status.PUBLISHED)
        self.message_user(request, f"{updated} produit(s) publié(s) après validation.")

    @admin.action(description="🚫 Rejeter (retour brouillon)")
    def reject_to_draft(self, request, queryset):
        updated = queryset.update(status=Product.Status.DRAFT)
        self.message_user(request, f"{updated} produit(s) renvoyé(s) en brouillon.")