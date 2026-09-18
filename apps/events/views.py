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
from .forms import EventForm, TicketTypeFormSet, EventFAQFormSet, EventGalleryItemFormSet, EventPartnerFormSet


# ============================================
# VUES PUBLIQUES
# ============================================

def event_list(request):
    """Liste publique des événements publiés."""
    from django.utils import timezone

    # Cache par query string (5 minutes)
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

    similar_events = Event.objects.filter(
        status=Event.Status.PUBLISHED,
        category=event.category
    ).exclude(pk=event.pk).order_by('-start_date')[:3]

    gallery_items = event.gallery_items.all()

    return render(request, 'events/detail.html', {
        'event':          event,
        'ticket_types':   ticket_types,
        'similar_events': similar_events,
        # Le même modèle EventGalleryItem sert les photos (sans heure) et
        # le programme (avec heure) — on sépare ici juste pour l'affichage.
        'program_items':  gallery_items.filter(time__isnull=False),
        'photo_items':    gallery_items.filter(time__isnull=True),
        'faqs':           event.faqs.all(),
        'partners':       event.partners.all(),
    })


# ============================================
# VUES ORGANISATEUR
# ============================================

def organizer_required(view_func):
    """Décorateur : réserve la vue aux organisateurs."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_organizer or request.user.is_platform_admin):
            messages.error(request, "Cette section est réservée aux organisateurs.")
            return redirect('accounts:profile')
        return view_func(request, *args, **kwargs)
    return wrapper


@organizer_required
def my_events(request):
    """Tableau de bord événements de l'organisateur."""
    events = Event.objects.filter(organizer=request.user).order_by('-created_at')

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
    form            = EventForm()
    formset         = TicketTypeFormSet()
    faq_formset     = EventFAQFormSet()
    gallery_formset = EventGalleryItemFormSet()
    partner_formset = EventPartnerFormSet()

    if request.method == 'POST':
        form            = EventForm(request.POST, request.FILES)
        formset         = TicketTypeFormSet(request.POST)
        faq_formset     = EventFAQFormSet(request.POST)
        gallery_formset = EventGalleryItemFormSet(request.POST, request.FILES)
        partner_formset = EventPartnerFormSet(request.POST, request.FILES)

        if (form.is_valid() and formset.is_valid() and faq_formset.is_valid()
                and gallery_formset.is_valid() and partner_formset.is_valid()):
            # ============================================
            # 🔒 VÉRIFICATION KYC AVANT PUBLICATION PAYANTE
            # ============================================
            event_status = form.cleaned_data.get('status')
            if event_status == Event.Status.PUBLISHED:
                # Vérifier si l'événement a des tickets payants
                has_paid_tickets = False
                for tt_form in formset:
                    if tt_form.cleaned_data and not tt_form.cleaned_data.get('DELETE', False):
                        if tt_form.cleaned_data.get('price', 0) > 0:
                            has_paid_tickets = True
                            break

                if has_paid_tickets and not request.user.is_organizer_verified:
                    messages.error(
                        request,
                        "🔒 Votre compte organisateur n'est pas encore vérifié. "
                        "Veuillez soumettre vos documents KYC (pièce d'identité, "
                        "justificatif de domicile, document professionnel) dans "
                        "votre profil avant de publier un événement payant."
                    )
                    return render(request, 'events/create.html', {
                        'form':            form,
                        'formset':         formset,
                        'faq_formset':     faq_formset,
                        'gallery_formset': gallery_formset,
                        'partner_formset': partner_formset,
                        'action':  'Créer',
                    })

            event = form.save(commit=False)
            event.organizer = request.user
            event.save()

            formset.instance = event
            formset.save()

            faq_formset.instance = event
            faq_formset.save()
            gallery_formset.instance = event
            gallery_formset.save()
            partner_formset.instance = event
            partner_formset.save()

            prices = event.ticket_types.values_list('price', flat=True)
            if prices:
                event.min_price = min(prices)
                event.save(update_fields=['min_price'])

            # Notification email de création d'événement.
            # L'envoi ne doit jamais empêcher la création de l'événement.
            try:
                from django.conf import settings
                from django.core.mail import EmailMultiAlternatives
                from django.template.loader import render_to_string
                from django.urls import reverse
                from django.utils import timezone

                organizer = request.user
                kyc_required = not organizer.is_organizer_verified
                profile_url = request.build_absolute_uri(
                    reverse('accounts:profile')
                )

                context = {
                    'organizer': organizer,
                    'event': event,
                    'kyc_required': kyc_required,
                    'profile_url': profile_url,
                    'platform_url': settings.PAYDUNYA_BASE_URL,
                    'support_email': getattr(
                        settings, 'DEFAULT_FROM_EMAIL', ''
                    ),
                    'year': timezone.now().year,
                }

                subject = f"Votre événement « {event.title} » a été créé — IvoirPass"
                text_body = render_to_string(
                    'notifications/email/event_created.txt',
                    context,
                )
                html_body = render_to_string(
                    'notifications/email/event_created.html',
                    context,
                )

                email = EmailMultiAlternatives(
                    subject=subject,
                    body=text_body,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    to=[organizer.email],
                )
                email.attach_alternative(html_body, "text/html")
                email.send(fail_silently=True)
            except Exception:
                pass

            messages.success(request, f"Événement « {event.title} » créé avec succès !")
            return redirect('events:my_events')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'events/create.html', {
        'form':            form,
        'formset':         formset,
        'faq_formset':     faq_formset,
        'gallery_formset': gallery_formset,
        'partner_formset': partner_formset,
        'action':  'Créer',
    })


@organizer_required
def event_edit(request, slug):
    """Modifier un événement existant."""
    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    form            = EventForm(instance=event)
    formset         = TicketTypeFormSet(instance=event)
    faq_formset     = EventFAQFormSet(instance=event)
    gallery_formset = EventGalleryItemFormSet(instance=event)
    partner_formset = EventPartnerFormSet(instance=event)

    if request.method == 'POST':
        form            = EventForm(request.POST, request.FILES, instance=event)
        formset         = TicketTypeFormSet(request.POST, instance=event)
        faq_formset     = EventFAQFormSet(request.POST, instance=event)
        gallery_formset = EventGalleryItemFormSet(request.POST, request.FILES, instance=event)
        partner_formset = EventPartnerFormSet(request.POST, request.FILES, instance=event)

        if (form.is_valid() and formset.is_valid() and faq_formset.is_valid()
                and gallery_formset.is_valid() and partner_formset.is_valid()):
            # ============================================
            # 🔒 VÉRIFICATION KYC AVANT PUBLICATION PAYANTE
            # ============================================
            event_status = form.cleaned_data.get('status')
            if event_status == Event.Status.PUBLISHED:
                has_paid_tickets = False
                for tt_form in formset:
                    if tt_form.cleaned_data and not tt_form.cleaned_data.get('DELETE', False):
                        if tt_form.cleaned_data.get('price', 0) > 0:
                            has_paid_tickets = True
                            break

                if has_paid_tickets and not request.user.is_organizer_verified:
                    messages.error(
                        request,
                        "🔒 Votre compte organisateur n'est pas encore vérifié. "
                        "Veuillez soumettre vos documents KYC dans votre profil "
                        "avant de publier un événement payant."
                    )
                    return render(request, 'events/create.html', {
                        'form':            form,
                        'formset':         formset,
                        'faq_formset':     faq_formset,
                        'gallery_formset': gallery_formset,
                        'partner_formset': partner_formset,
                        'event':   event,
                        'action':  'Modifier',
                    })

            event = form.save()
            formset.save()
            faq_formset.save()
            gallery_formset.save()
            partner_formset.save()

            prices = event.ticket_types.values_list('price', flat=True)
            if prices:
                event.min_price = min(prices)
                event.save(update_fields=['min_price'])

            messages.success(request, "Événement mis à jour.")
            return redirect('events:my_events')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'events/create.html', {
        'form':            form,
        'formset':         formset,
        'faq_formset':     faq_formset,
        'gallery_formset': gallery_formset,
        'partner_formset': partner_formset,
        'event':   event,
        'action':  'Modifier',
    })


@organizer_required
def event_delete(request, slug):
    event = get_object_or_404(Event, slug=slug, organizer=request.user)

    if request.method == 'POST':
        if event.tickets_sold > 0:
            from .services import cancel_event_and_refund

            result = cancel_event_and_refund(event)

            messages.warning(
                request,
                f"Événement annulé. {result['orders_refunded']} commande(s) "
                f"client(s) concernée(s) par le remboursement."
            )
        else:
            title = event.title
            event.delete()
            messages.success(request, f"Événement « {title} » supprimé.")

    return redirect('events:my_events')

@organizer_required
def assign_scanner_agents(request, slug):
    """
    Permet à l'organisateur d'assigner des agents scanner (comptes avec
    le rôle 'scanner') à cet événement précis — sans assignation, un
    agent scanner ne peut plus scanner l'événement (voir Event.scanner_agents).

    Portée strictement limitée aux agents de CET organisateur (CustomUser.managed_by)
    — avant ce correctif, la liste montrait TOUS les agents scanner de la
    plateforme, tous organisateurs confondus (fuite d'email/nom entre
    organisateurs sans lien entre eux, et possibilité d'assigner l'agent
    d'un autre organisateur à son propre événement sans son accord).

    Les agents déjà assignés à CET événement avant ce correctif (pool
    global historique, managed_by non renseigné) restent visibles et
    modifiables ici pour ne pas casser une assignation existante, mais
    aucun autre agent "orphelin" n'apparaît.
    """
    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    from apps.accounts.models import CustomUser
    from django.db.models import Q

    already_on_this_event = event.scanner_agents.values_list('id', flat=True)
    allowed_agents = CustomUser.objects.filter(
        Q(managed_by=request.user) | Q(id__in=already_on_this_event),
        role='scanner', is_active=True,
    ).distinct().order_by('email')

    if request.method == 'POST':
        selected_ids = request.POST.getlist('agents')
        # On ne retient QUE les agents que l'organisateur a le droit
        # d'assigner (mêmes règles que l'affichage ci-dessus) — sans ce
        # filtre, un POST forgé avec l'ID d'un agent d'un autre
        # organisateur aurait pu l'assigner malgré tout.
        event.scanner_agents.set(allowed_agents.filter(id__in=selected_ids))
        messages.success(
            request,
            f"{event.scanner_agents.count()} agent(s) assigné(s) à « {event.title} »."
        )
        return redirect('events:assign_scanner_agents', slug=event.slug)

    assigned_ids = set(event.scanner_agents.values_list('id', flat=True))

    return render(request, 'events/assign_scanner_agents.html', {
        'event': event,
        'all_agents': allowed_agents,
        'assigned_ids': assigned_ids,
    })


@organizer_required
def create_scanner_agent(request):
    """
    Permet à l'organisateur de créer lui-même un agent scanner, plutôt que
    de dépendre d'un admin à chaque fois (voir audit — goulot d'étranglement
    identifié). Le compte créé est automatiquement rattaché à cet
    organisateur (managed_by) et son email est marqué vérifié d'emblée :
    c'est l'organisateur qui crée sciemment ce compte de service pour son
    propre personnel, la vérification d'email par lien n'a pas de sens ici
    (voir audit — bug corrigé où un agent créé sans email vérifié ne
    pouvait jamais se connecter).
    """
    from apps.accounts.models import CustomUser
    from allauth.account.models import EmailAddress
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        password = request.POST.get('password', '')

        errors = []
        if not email:
            errors.append("L'email est obligatoire.")
        elif CustomUser.objects.filter(email=email).exists():
            errors.append("Un compte existe déjà avec cet email.")
        if not password:
            errors.append("Le mot de passe est obligatoire.")
        else:
            try:
                validate_password(password)
            except ValidationError as e:
                errors.extend(e.messages)

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            agent = CustomUser.objects.create_user(
                email=email, password=password,
                first_name=first_name, last_name=last_name,
                role=CustomUser.Role.SCANNER,
                managed_by=request.user,
            )
            EmailAddress.objects.create(
                user=agent, email=agent.email, primary=True, verified=True,
            )
            messages.success(request, f"Agent scanner {email} créé — vous pouvez maintenant l'assigner à vos événements.")
            return redirect('events:my_events')

    return render(request, 'events/create_scanner_agent.html')