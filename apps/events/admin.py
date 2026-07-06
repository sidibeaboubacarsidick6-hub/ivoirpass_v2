"""
IvoirPass V2 — Administration des événements
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import Category, Event, TicketType


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'color_preview', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}

    def color_preview(self, obj):
        return format_html(
            '<span style="display:inline-block; width:20px; height:20px; '
            'background:{}; border-radius:4px; border:1px solid #ddd;"></span>',
            obj.color
        )
    color_preview.short_description = "Couleur"


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 1
    fields = (
        'name', 'price', 'quantity',
        'quantity_sold', 'max_per_order', 'is_visible', 'order'
    )
    readonly_fields = ('quantity_sold',)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'organizer', 'category', 'status',
        'start_date', 'venue_city', 'tickets_sold',
        'commission_rate', 'is_featured', 'cover_preview'
    )
    list_filter = ('status', 'category', 'event_type', 'is_featured', 'venue_city')
    search_fields = ('title', 'organizer__email', 'venue_name', 'venue_city')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = (
        'uuid', 'tickets_sold', 'created_at',
        'updated_at', 'published_at', 'cover_preview'
    )
    date_hierarchy = 'start_date'
    inlines = [TicketTypeInline]

    fieldsets = (
        ('Informations principales', {
            'fields': (
                'title', 'subtitle', 'slug', 'uuid',
                'description', 'short_description',
                'category', 'tags', 'organizer'
            )
        }),
        ('Dates', {
            'fields': (
                'start_date', 'end_date', 'doors_open',
                'sale_start', 'sale_end'
            )
        }),
        ('Lieu', {
            'fields': (
                'event_type', 'venue_name', 'venue_address',
                'venue_city', 'venue_country',
                'venue_latitude', 'venue_longitude', 'online_link'
            )
        }),
        ('Médias', {
            'fields': (
                'cover_image', 'cover_preview',
                'thumbnail', 'video_url'
            )
        }),
        ('Billetterie', {
            'fields': (
                'is_free', 'min_price',
                'total_capacity', 'tickets_sold'
            )
        }),
        ('Statut', {
            'fields': (
                'status', 'is_featured',
                'requires_approval', 'published_at'
            )
        }),
        ('Commission IvoirPass', {
            'fields': (
                'commission_rate',
                'commission_negotiated',
                'commission_note',
            ),
            'description': (
                '⚠️ La commission est prélevée sur le reversement '
                'de l\'organisateur, pas sur le prix affiché à l\'acheteur.'
            ),
        }),
        ('Système', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['publish_events', 'cancel_events', 'feature_events']

    def cover_preview(self, obj):
        if obj.cover_image:
            return format_html(
                '<img src="{}" style="max-height:120px; border-radius:8px;" />',
                obj.cover_image.url
            )
        return "Aucune image"
    cover_preview.short_description = "Aperçu"

    @admin.action(description="✅ Publier les événements sélectionnés")
    def publish_events(self, request, queryset):
        updated = queryset.filter(
            status=Event.Status.DRAFT
        ).update(status=Event.Status.PUBLISHED)
        self.message_user(request, f"{updated} événement(s) publié(s).")

    @admin.action(description="🚫 Annuler les événements sélectionnés")
    def cancel_events(self, request, queryset):
        updated = queryset.update(status=Event.Status.CANCELLED)
        self.message_user(request, f"{updated} événement(s) annulé(s).")

    @admin.action(description="⭐ Mettre en avant")
    def feature_events(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f"{updated} événement(s) mis en avant.")


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = (
        'event', 'name', 'price', 'quantity',
        'quantity_sold', 'remaining_display', 'is_visible'
    )
    list_filter = ('is_visible', 'event__status')
    search_fields = ('event__title', 'name')

    def remaining_display(self, obj):
        r = obj.remaining
        return "Illimité" if r is None else r
    remaining_display.short_description = "Restants"