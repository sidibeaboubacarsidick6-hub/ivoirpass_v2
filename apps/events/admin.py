"""
IvoirPass V2 — Administration des événements
"""
from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from apps.dashboard.models import AuditLog
from apps.dashboard.services import log_action

from .models import Category, Event, TicketType, EventFAQ, EventGalleryItem, EventPartner


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


class EventFAQInline(admin.TabularInline):
    model = EventFAQ
    extra = 1
    fields = ('question', 'answer', 'order')


class EventGalleryItemInline(admin.TabularInline):
    model = EventGalleryItem
    extra = 1
    fields = ('image', 'title', 'subtitle', 'time', 'order')
    verbose_name = "Photo galerie ou entrée de programme"
    verbose_name_plural = "Galerie / Programme (renseigner 'heure' pour une entrée de programme)"


class EventPartnerInline(admin.TabularInline):
    model = EventPartner
    extra = 1
    fields = ('name', 'logo', 'website_url', 'order')

class IncreaseFreeQuotaForm(forms.Form):
    """Formulaire intermédiaire pour l'action bulk d'augmentation de quota."""
    new_quota = forms.IntegerField(
        label="Nouveau quota de codes gratuits",
        min_value=0,
        max_value=10000,
        initial=50,
        help_text="S'appliquera à tous les événements sélectionnés.",
    )
    reason = forms.CharField(
        label="Raison (optionnel)",
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'vLargeTextField'}),
        help_text="Ex : demande de l'organisateur pour un événement VIP.",
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'organizer', 'category', 'status_badge',
        'start_date', 'venue_city', 'tickets_sold',
        'commission_rate', 'is_featured', 'cover_preview'
    )

    @admin.display(description="Statut", ordering='status')
    def status_badge(self, obj):
        """Affiche un badge coloré selon le statut de l'événement."""
        color = {
            'draft': '#6c757d',
            'published': '#1B7A3E',
            'cancelled': '#dc3545',
            'completed': '#0dcaf0',
            'postponed': '#F47920',
            'cancel_pending': '#ff6b35',
        }.get(obj.status, '#6c757d')

        icon = '🚨 ' if obj.status == 'cancel_pending' else ''

        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;'
            'border-radius:12px;font-size:0.78rem;font-weight:700;">'
            '{}{}</span>',
            color, icon, obj.get_status_display()
        )

    list_filter = ('status', 'category', 'event_type', 'is_featured', 'venue_city')
    search_fields = ('title', 'organizer__email', 'venue_name', 'venue_city')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = (
        'uuid', 'tickets_sold', 'created_at',
        'updated_at', 'published_at', 'cover_preview',
        'cancel_requested_at', 'cancel_requested_by', 'cancel_request_reason',
    )
    date_hierarchy = 'start_date'
    inlines = [TicketTypeInline, EventGalleryItemInline, EventFAQInline, EventPartnerInline]

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
                'min_price',
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
        ('🚨 Annulation en attente de validation', {
            'fields': (
                'cancel_requested_at',
                'cancel_requested_by',
                'cancel_request_reason',
            ),
            'description': (
                '⚠️ L\'organisateur a demandé l\'annulation de cet événement '
                'car son wallet est insuffisant pour couvrir les remboursements. '
                'Validez ou refusez la demande avec les actions en haut de la liste.'
            ),
            'classes': ('collapse',),
        }),
        ('Système', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

        # ============================================
    # 🎫 ACTION BULK : augmenter le quota de codes gratuits (Vague 2.2 S4)
    # ============================================

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'increase-free-quota/',
                self.admin_site.admin_view(self.increase_free_quota_view),
                name='events_event_increase_free_quota',
            ),
        ]
        return custom + urls

    @admin.action(description="🎫 Augmenter le quota de codes gratuits")
    def increase_free_quota(self, request, queryset):
        """Redirige vers le formulaire intermédiaire."""
        pks = ','.join(str(pk) for pk in queryset.values_list('pk', flat=True))
        url = reverse('admin:events_event_increase_free_quota')
        return HttpResponseRedirect(f'{url}?ids={pks}')

    def increase_free_quota_view(self, request):
        """Vue intermédiaire : saisir le nouveau quota et l'appliquer."""
        ids_raw = request.GET.get('ids', '') or request.POST.get('ids', '')
        ids = [int(pk) for pk in ids_raw.split(',') if pk.strip().isdigit()]
        events = Event.objects.filter(pk__in=ids)

        if not events.exists():
            self.message_user(
                request, "Aucun événement sélectionné.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(reverse('admin:events_event_changelist'))

        if request.method == 'POST':
            form = IncreaseFreeQuotaForm(request.POST)
            if form.is_valid():
                new_quota = form.cleaned_data['new_quota']
                reason = form.cleaned_data.get('reason', '').strip()
                updated_count = 0

                for event in events:
                    old_quota = event.free_tickets_quota
                    if old_quota == new_quota:
                        continue
                    event.free_tickets_quota = new_quota
                    event.save(update_fields=['free_tickets_quota'])
                    updated_count += 1

                    log_action(
                        action=AuditLog.Action.FREE_TICKETS_QUOTA_CHANGED,
                        description=(
                            f"Quota de codes gratuits modifié pour "
                            f"« {event.title} » : {old_quota} → {new_quota}."
                            + (f" Raison : {reason}" if reason else "")
                        ),
                        user=request.user,
                        obj=event,
                        metadata={
                            'old_quota': old_quota,
                            'new_quota': new_quota,
                            'reason':    reason,
                        },
                        ip_address=request.META.get('REMOTE_ADDR'),
                    )

                self.message_user(
                    request,
                    f"Quota mis à jour pour {updated_count} événement(s) "
                    f"(sur {events.count()} sélectionné(s)).",
                )
                return HttpResponseRedirect(reverse('admin:events_event_changelist'))
        else:
            form = IncreaseFreeQuotaForm()

        context = {
            **self.admin_site.each_context(request),
            'title':  "Augmenter le quota de codes gratuits",
            'events': events,
            'form':   form,
            'ids':    ids_raw,
            'opts':   self.model._meta,
        }
        return TemplateResponse(
            request,
            'admin/events/increase_free_quota.html',
            context,
        )

    actions = [
        'publish_events', 'cancel_events', 'feature_events',
        'increase_free_quota',
        'approve_cancellation', 'refuse_cancellation',
    ]

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
        from .services import cancel_event_organizer_liable

        cancelled = 0
        orders_affected = 0
        tickets_voided = 0
        wallets_frozen = 0
        blocked = []

        for event in queryset:
            try:
                result = cancel_event_organizer_liable(
                    event,
                    reason=f"Annulation admin par {request.user.email}",
                )
            except ValueError as exc:
                # Cas inhabituel n°1 : litige en cours → on bloque
                blocked.append(f"{event.title} : {exc}")
                continue

            cancelled += 1
            orders_affected += result['orders_affected']
            tickets_voided += result['tickets_voided']
            if result['wallet_frozen']:
                wallets_frozen += 1

        if cancelled:
            self.message_user(
                request,
                f"{cancelled} événement(s) annulé(s). "
                f"{orders_affected} commande(s) impactée(s), "
                f"{tickets_voided} billet(s) invalidé(s), "
                f"{wallets_frozen} wallet(s) gelé(s)."
            )

        if blocked:
            messages.error(
                request,
                "Annulation bloquée pour : " + " | ".join(blocked),
            )

    @admin.action(description="⭐ Mettre en avant")
    def feature_events(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f"{updated} événement(s) mis en avant.")



    # ============================================================
    # CAS INHABITUEL N°2 — Validation / Refus des demandes d'annulation
    # ============================================================

    @admin.action(description="✅ Valider la demande d'annulation (Cas 2)")
    def approve_cancellation(self, request, queryset):
        """
        Valide une ou plusieurs demandes d'annulation en attente.

        Pour chaque événement en CANCEL_PENDING :
          - Appelle cancel_event_organizer_liable() qui déclenche
            l'annulation complète (billets void, commandes annulées,
            wallet gelé, emails aux acheteurs).
          - Notifie l'organisateur par email.
        """
        from apps.notifications.service import NotificationService
        from .services import cancel_event_organizer_liable


        pending = queryset.filter(status=Event.Status.CANCEL_PENDING)

        if not pending.exists():
            self.message_user(
                request,
                "Aucun événement en attente d'annulation dans la sélection.",
                level=messages.WARNING,
            )
            return

        approved = 0
        errors = []

        for event in pending:
            try:
                result = cancel_event_organizer_liable(
                    event,
                    reason=(
                        f"Annulation validée par admin ({request.user.email}) — "
                        f"demande initiale : {event.cancel_request_reason or 'sans raison'}"
                    ),
                )

                # Notifier l'organisateur
                if event.organizer and event.organizer.email:
                    try:
                        NotificationService.send_email(
                            subject=f"[IvoirPass] Annulation validée : {event.title}",
                            message=(
                                f"Bonjour {event.organizer.get_full_name() or event.organizer.email},\n\n"
                                f"Votre demande d'annulation pour l'événement "
                                f"« {event.title} » a été validée par un administrateur IvoirPass.\n\n"
                                f"Effets :\n"
                                f"- {result['orders_affected']} commande(s) annulée(s)\n"
                                f"- {result['tickets_voided']} billet(s) invalidé(s)\n"
                                f"- Wallet : {'gelé' if result['wallet_frozen'] else 'non impacté'}\n\n"
                                f"Vous êtes responsable du remboursement des acheteurs. "
                                f"Votre wallet reste gelé jusqu'à régularisation.\n\n"
                                f"L'équipe IvoirPass"
                            ),
                            recipient_list=[event.organizer.email],
                        )
                    except Exception as exc:
                        import logging
                        logging.getLogger(__name__).exception(
                            "Échec notification organisateur %s : %s",
                            event.organizer.email, exc,
                        )

                # Log audit
                log_action(
                    action=AuditLog.Action.UPDATE,
                    description=(
                        f"Annulation validée par admin pour « {event.title} » — "
                        f"{result['orders_affected']} commande(s), "
                        f"{result['tickets_voided']} billet(s) invalidé(s)."
                    ),
                    user=request.user,
                    obj=event,
                    metadata={
                        'orders_affected': result['orders_affected'],
                        'tickets_voided': result['tickets_voided'],
                        'wallet_frozen': result['wallet_frozen'],
                    },
                    ip_address=request.META.get('REMOTE_ADDR'),
                )

                approved += 1

            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception(
                    "approve_cancellation : échec pour event %s", event.pk,
                )
                errors.append(f"« {event.title} » : {exc}")

        if approved:
            self.message_user(
                request,
                f"{approved} demande(s) d'annulation validée(s) et appliquée(s).",
            )
        if errors:
            messages.error(request, "Erreurs : " + " | ".join(errors))

    @admin.action(description="🚫 Refuser la demande d'annulation (Cas 2)")
    def refuse_cancellation(self, request, queryset):
        """
        Refuse une ou plusieurs demandes d'annulation.

        Pour chaque événement en CANCEL_PENDING :
          - Restaure le statut PUBLISHED
          - Efface les 3 champs de demande
          - Notifie l'organisateur par email
        """
        from apps.notifications.service import NotificationService
        from django.utils import timezone

        pending = queryset.filter(status=Event.Status.CANCEL_PENDING)

        if not pending.exists():
            self.message_user(
                request,
                "Aucun événement en attente d'annulation dans la sélection.",
                level=messages.WARNING,
            )
            return

        refused = 0

        for event in pending:
            old_reason = event.cancel_request_reason

            event.status = Event.Status.PUBLISHED
            event.cancel_requested_at = None
            event.cancel_requested_by = None
            event.cancel_request_reason = ''
            event.save(update_fields=[
                'status', 'cancel_requested_at',
                'cancel_requested_by', 'cancel_request_reason',
            ])

            # Notifier l'organisateur
            if event.organizer and event.organizer.email:
                try:
                    NotificationService.send_email(
                        subject=f"[IvoirPass] Demande d'annulation refusée : {event.title}",
                        message=(
                            f"Bonjour {event.organizer.get_full_name() or event.organizer.email},\n\n"
                            f"Votre demande d'annulation pour l'événement "
                            f"« {event.title} » a été examinée et refusée.\n\n"
                            f"Raison invoquée : {old_reason or 'non précisée'}\n\n"
                            f"L'événement reste publié et actif. Si vous souhaitez "
                            f"discuter de cette décision, contactez le support IvoirPass.\n\n"
                            f"L'équipe IvoirPass"
                        ),
                        recipient_list=[event.organizer.email],
                    )
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).exception(
                        "Échec notification organisateur %s : %s",
                        event.organizer.email, exc,
                    )

            log_action(
                action=AuditLog.Action.UPDATE,
                description=(
                    f"Demande d'annulation refusée pour « {event.title} » — "
                    f"raison initiale : {old_reason or 'non précisée'}."
                ),
                user=request.user,
                obj=event,
                metadata={'old_reason': old_reason},
                ip_address=request.META.get('REMOTE_ADDR'),
            )

            refused += 1

        if refused:
            self.message_user(
                request,
                f"{refused} demande(s) d'annulation refusée(s). Événement(s) remis en publié.",
            )

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