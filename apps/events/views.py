"""
IvoirPass V2 — Vues des événements
"""
from django.core.cache import cache
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from .models import Event, Category, TicketType
from .forms import EventForm, TicketTypeFormSet


# ============================================
# VUES PUBLIQUES
# ============================================

def event_list(request):
    """Liste publique des événements publiés."""
    from django.utils import timezone

    # 🔥 Cache par query string (5 minutes)
    query = request.GET.get('q', '')
    category_slug = request.GET.get('category', '')
    city = request.GET.get('city', '')
    upcoming_only = request.GET.get('upcoming', '')
    page_number = request.GET.get('page', 1)
    
    cache_key = f'event_list_{query}_{category_slug}_{city}_{upcoming_only}_page_{page_number}'
    cached_data = cache.get(cache_key)
    
    if cached_data is not None:
        return render(request, 'events/list.html', cached_data)

    events = Event.objects.filter(
        status=Event.Status.PUBLISHED
    ).select_related('category', 'organizer')

    if query:
        events = events.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(venue_city__icontains=query) |
            Q(tags__icontains=query)
        )

    if category_slug:
        events = events.filter(category__slug=category_slug)

    if city:
        events = events.filter(venue_city__icontains=city)

    if upcoming_only:
        events = events.filter(start_date__gte=timezone.now())

    paginator = Paginator(events, 12)
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.filter(is_active=True)

    context = {
        'page_obj':      page_obj,
        'categories':    categories,
        'query':         query,
        'category_slug': category_slug,
        'city':          city,
        'total':         paginator.count,
    }
    
    cache.set(cache_key, context, 300)
    return render(request, 'events/list.html', context)


def event_detail(request, slug):
    """Page de détail d'un événement."""
    event = get_object_or_404(
        Event.objects.select_related('category', 'organizer'),
        slug=slug,
        status=Event.Status.PUBLISHED
    )
    ticket_types = event.ticket_types.filter(is_visible=True).order_by('order', 'price')

    # Événements similaires
    similar_events = Event.objects.filter(
        status=Event.Status.PUBLISHED,
        category=event.category
    ).exclude(pk=event.pk).order_by('-start_date')[:3]

    return render(request, 'events/detail.html', {
        'event':          event,
        'ticket_types':   ticket_types,
        'similar_events': similar_events,
    })


# ============================================
# VUES ORGANISATEUR
# ============================================

def organizer_required(view_func):
    """Décorateur : réserve la vue aux organisateurs."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_organizer or request.user.is_platform_admin):
            messages.error(
                request,
                "Cette section est réservée aux organisateurs."
            )
            return redirect('accounts:profile')
        return view_func(request, *args, **kwargs)
    return wrapper


@organizer_required
def my_events(request):
    """Tableau de bord événements de l'organisateur."""
    events = Event.objects.filter(
        organizer=request.user
    ).order_by('-created_at')

    # Statistiques rapides
    stats = {
        'total':     events.count(),
        'published': events.filter(status=Event.Status.PUBLISHED).count(),
        'draft':     events.filter(status=Event.Status.DRAFT).count(),
        'tickets_sold': sum(e.tickets_sold for e in events),
    }

    return render(request, 'events/my_events.html', {
        'events': events,
        'stats':  stats,
    })


@organizer_required
def event_create(request):
    """Créer un nouvel événement."""
    form       = EventForm()
    formset    = TicketTypeFormSet()

    if request.method == 'POST':
        form    = EventForm(request.POST, request.FILES)
        formset = TicketTypeFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            event = form.save(commit=False)
            event.organizer = request.user
            event.save()

            # Sauvegarde les types de tickets
            formset.instance = event
            formset.save()

            # Met à jour le prix minimum
            prices = event.ticket_types.values_list('price', flat=True)
            if prices:
                event.min_price = min(prices)
                event.save(update_fields=['min_price'])

            messages.success(
                request,
                f"Événement « {event.title} » créé avec succès !"
            )
            return redirect('events:my_events')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'events/create.html', {
        'form':    form,
        'formset': formset,
        'action':  'Créer',
    })


@organizer_required
def event_edit(request, slug):
    """Modifier un événement existant."""
    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    form    = EventForm(instance=event)
    formset = TicketTypeFormSet(instance=event)

    if request.method == 'POST':
        form    = EventForm(request.POST, request.FILES, instance=event)
        formset = TicketTypeFormSet(request.POST, instance=event)

        if form.is_valid() and formset.is_valid():
            event = form.save()
            formset.save()

            prices = event.ticket_types.values_list('price', flat=True)
            if prices:
                event.min_price = min(prices)
                event.save(update_fields=['min_price'])

            messages.success(request, "Événement mis à jour.")
            return redirect('events:my_events')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'events/create.html', {
        'form':    form,
        'formset': formset,
        'event':   event,
        'action':  'Modifier',
    })


@organizer_required
def event_delete(request, slug):
    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    if request.method == 'POST':
        if event.tickets_sold > 0:
            event.status = Event.Status.CANCELLED
            event.save()

            # Notifie tous les acheteurs et déclenche remboursement
            from apps.tickets.models import Ticket
            from apps.notifications.service import NotificationService

            tickets = Ticket.objects.filter(
                order_item__ticket_type__event=event,
                order_item__order__status='paid',
                status='valid',
            ).select_related('order_item__order')

            orders_refunded = set()
            for ticket in tickets:
                order = ticket.order_item.order
                if order.id not in orders_refunded:
                    order.refund(reason='Événement annulé par organisateur')
                    orders_refunded.add(order.id)
                NotificationService.event_cancelled(ticket)

            messages.warning(
                request,
                f"Événement annulé. {len(orders_refunded)} commande(s) "
                f"marquée(s) pour remboursement et clients notifiés."
            )
        else:
            title = event.title
            event.delete()
            messages.success(request, f"Événement « {title} » supprimé.")
    return redirect('events:my_events')