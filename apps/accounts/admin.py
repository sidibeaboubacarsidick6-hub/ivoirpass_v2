"""
IvoirPass V2 — Administration des utilisateurs
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from .models import CustomUser, UserAddress


class UserAddressInline(admin.TabularInline):
    """Affiche les adresses directement dans la fiche utilisateur."""
    model = UserAddress
    extra = 0
    fields = ('label', 'full_name', 'phone', 'city', 'zone', 'is_default')
    readonly_fields = ('shipping_cost_display',)

    def shipping_cost_display(self, obj):
        return f"{obj.shipping_cost} FCFA" if obj.pk else "-"
    shipping_cost_display.short_description = "Frais livraison"


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Administration personnalisée des utilisateurs IvoirPass."""

    # Colonnes affichées dans la liste
    list_display = (
        'email', 'get_full_name', 'role', 'phone_number',
        'city', 'is_organizer_verified', 'is_active', 'date_joined'
    )

    # Filtres dans la sidebar
    list_filter = (
        'role', 'is_active', 'is_staff',
        'is_organizer_verified', 'city', 'preferred_language'
    )

    # Champs de recherche
    search_fields = (
        'email', 'first_name', 'last_name',
        'phone_number', 'organization_name'
    )

    # Ordre de tri par défaut
    ordering = ('-date_joined',)

    # Champs en lecture seule
    readonly_fields = ('date_joined', 'last_login', 'updated_at', 'avatar_preview')

    # Onglets de la fiche utilisateur
    fieldsets = (
        (_('Identifiants'), {
            'fields': ('email', 'password')
        }),
        (_('Informations personnelles'), {
            'fields': (
                'first_name', 'last_name', 'phone_number',
                'city', 'preferred_language', 'bio',
                'avatar', 'avatar_preview'
            )
        }),
        (_('Rôle & Permissions'), {
            'fields': (
                'role', 'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions'
            )
        }),
        (_('Organisateur (KYC)'), {
            'fields': (
                'is_organizer_verified',
                'organization_name',
                'organization_description',
                'organization_logo',
                'organization_website',
            ),
            'classes': ('collapse',),
        }),
        (_('Préférences notifications'), {
            'fields': ('notify_email', 'notify_sms', 'notify_push'),
            'classes': ('collapse',),
        }),
        (_('Dates'), {
            'fields': ('date_joined', 'last_login', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # Champs pour la création d'un utilisateur depuis l'admin
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email', 'first_name', 'last_name',
                'phone_number', 'role', 'password1', 'password2'
            ),
        }),
    )

    # Affichage en ligne des adresses
    inlines = [UserAddressInline]

    def avatar_preview(self, obj):
        """Aperçu de l'avatar dans l'admin."""
        if obj.avatar:
            return format_html(
                '<img src="{}" width="80" height="80" '
                'style="border-radius:50%; object-fit:cover;" />',
                obj.avatar.url
            )
        return "Aucun avatar"
    avatar_preview.short_description = "Aperçu"

    def get_full_name(self, obj):
        return obj.get_full_name()
    get_full_name.short_description = "Nom complet"

    # Actions personnalisées
    actions = ['verify_organizers', 'deactivate_users', 'activate_users']

    @admin.action(description="✅ Certifier les organisateurs sélectionnés")
    def verify_organizers(self, request, queryset):
        updated = queryset.filter(
            role=CustomUser.Role.ORGANIZER
        ).update(is_organizer_verified=True)
        self.message_user(
            request,
            f"{updated} organisateur(s) certifié(s) avec succès."
        )

    @admin.action(description="🚫 Désactiver les comptes sélectionnés")
    def deactivate_users(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} compte(s) désactivé(s).")

    @admin.action(description="✅ Activer les comptes sélectionnés")
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} compte(s) activé(s).")


@admin.register(UserAddress)
class UserAddressAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'label', 'full_name', 'city',
        'zone', 'is_default', 'shipping_cost_display'
    )
    list_filter = ('zone', 'is_default', 'city')
    search_fields = ('user__email', 'full_name', 'city')

    def shipping_cost_display(self, obj):
        return f"{obj.shipping_cost} FCFA"
    shipping_cost_display.short_description = "Frais livraison"