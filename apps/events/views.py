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
from django.views.decorators.http import require_POST
from django.db.models import F


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
                        "🔒 Pour publier un événement payant, vous devez d'abord "
                        "compléter votre KYC. Rendez-vous dans votre espace compte, "
                        "cliquez sur \"Mon profil\", cliquez sur \"Organisation\", "
                        "\"Complétez mon profil organisateur\", puis dans "
                        "\"Vérifications KYC\" téléchargez votre CNI et cliquez sur "
                        "\"Enregistrer\" pour terminer. Une fois confirmé, vous pourrez "
                        "publier des événements payants.",
                        extra_tags='danger kyc-persistent'
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
                        "🔒 Pour publier un événement payant, vous devez d'abord "
                        "compléter votre KYC. Rendez-vous dans votre espace compte, "
                        "cliquez sur \"Mon profil\", cliquez sur \"Organisation\", "
                        "\"Complétez mon profil organisateur\", puis dans "
                        "\"Vérifications KYC\" téléchargez votre CNI et cliquez sur "
                        "\"Enregistrer\" pour terminer. Une fois confirmé, vous pourrez "
                        "publier des événements payants.",
                        extra_tags='danger kyc-persistent'
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
            from .services import cancel_event_organizer_liable

            reason = request.POST.get(
                'cancel_reason',
                "Événement annulé par l'organisateur",
            )
            result = cancel_event_organizer_liable(event, reason=reason)

            msg = (
                f"Événement annulé. {result['orders_affected']} commande(s) "
                f"impactée(s), {result['tickets_voided']} billet(s) invalidé(s)."
            )
            if result['wallet_frozen']:
                msg += (
                    " Votre wallet a été gelé : aucune demande de "
                    "reversement ne sera acceptée tant qu'un administrateur "
                    "n'a pas régularisé la situation. Les acheteurs ont "
                    "été informés que vous procéderez au remboursement."
                )
            messages.warning(request, msg)
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

# ============================================
# 🎫 CODES DE BILLETS GRATUITS (Vague 2.2 — 2026-09-30)
# ============================================

@organizer_required
def free_tickets_list(request, slug):
    """Liste des codes de billets gratuits générés pour l'événement."""
    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    codes = event.free_ticket_codes.select_related(
        'ticket_type', 'guest_ticket'
    ).order_by('-created_at')

    used_count = codes.filter(used_at__isnull=False).count()
    remaining_quota = max(0, event.free_tickets_quota - event.free_tickets_generated)

    return render(request, 'events/free_tickets_list.html', {
        'event':           event,
        'codes':           codes,
        'used_count':      used_count,
        'remaining_quota': remaining_quota,
        'ticket_types':    event.ticket_types.all(),
    })


@organizer_required
@require_POST
def generate_free_tickets(request, slug):
    """
    Génère N codes de billets gratuits à partir d'un textarea.

    Format attendu : 1 ligne = "Nom Prénom, email@domain.com"
    """
    import re
    from django.db import transaction
    from apps.tickets.models import FreeTicketCode
    from apps.dashboard.models import AuditLog
    from apps.dashboard.services import log_action

    event = get_object_or_404(Event, slug=slug, organizer=request.user)

    # --- 1. Parser le textarea ---
    raw = request.POST.get('beneficiaries', '').strip()
    if not raw:
        messages.error(request, "Veuillez saisir au moins un bénéficiaire.")
        return redirect('events:free_tickets_list', slug=event.slug)

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    beneficiaries = []
    errors = []
    email_re = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

    for i, line in enumerate(lines, start=1):
        # Accepte virgule OU point-virgule OU tab comme séparateur
        parts = re.split(r'[;,\t]', line, maxsplit=1)
        if len(parts) != 2:
            errors.append(f"Ligne {i} : format invalide (attendu 'Nom, email').")
            continue
        name, email = parts[0].strip(), parts[1].strip()
        if not name:
            errors.append(f"Ligne {i} : nom vide.")
            continue
        if not email_re.match(email):
            errors.append(f"Ligne {i} : email invalide ({email}).")
            continue
        beneficiaries.append({'name': name, 'email': email})

    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect('events:free_tickets_list', slug=event.slug)

    if not beneficiaries:
        messages.error(request, "Aucun bénéficiaire valide détecté.")
        return redirect('events:free_tickets_list', slug=event.slug)

    # --- 2. Vérifier le quota ---
    count = len(beneficiaries)
    if event.free_tickets_generated + count > event.free_tickets_quota:
        remaining = max(0, event.free_tickets_quota - event.free_tickets_generated)
        messages.error(
            request,
            f"Quota dépassé : {count} demandé(s), {remaining} restant(s) "
            f"sur {event.free_tickets_quota}. Contactez l'administration "
            f"pour augmenter votre quota."
        )
        return redirect('events:free_tickets_list', slug=event.slug)

    # --- 3. Type de ticket (optionnel) ---
    ticket_type_id = request.POST.get('ticket_type')
    ticket_type = None
    if ticket_type_id:
        ticket_type = event.ticket_types.filter(pk=ticket_type_id).first()
    if not ticket_type:
        ticket_type = event.ticket_types.order_by('order', 'price').first()

    # --- 4. Créer les codes en transaction ---
    with transaction.atomic():
        created = []
        for b in beneficiaries:
            code = FreeTicketCode.objects.create(
                event=event,
                ticket_type=ticket_type,
                code=FreeTicketCode.generate_code(),
                beneficiary_name=b['name'],
                beneficiary_email=b['email'],
                created_by=request.user,
            )
            created.append(code)

        event.free_tickets_generated = F('free_tickets_generated') + count
        event.save(update_fields=['free_tickets_generated'])

        log_action(
            action=AuditLog.Action.FREE_TICKETS_GENERATED,
            description=(
                f"{count} code(s) de billet(s) gratuit(s) généré(s) "
                f"pour « {event.title} »."
            ),
            user=request.user,
            obj=event,
            metadata={
                'event_slug': event.slug,
                'count':      count,
                'ticket_type': ticket_type.name if ticket_type else None,
            },
            ip_address=request.META.get('REMOTE_ADDR'),
        )

    messages.success(
        request,
        f"{count} code(s) de billet(s) gratuit(s) généré(s). "
        f"Vous pouvez les copier ou télécharger le CSV."
    )
    return redirect('events:free_tickets_list', slug=event.slug)


@organizer_required
def download_free_tickets_csv(request, slug):
    """Export CSV des codes de billets gratuits."""
    import csv
    from django.http import HttpResponse

    event = get_object_or_404(Event, slug=slug, organizer=request.user)
    codes = event.free_ticket_codes.order_by('created_at')

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="codes-gratuits-{event.slug}.csv"'
    )
    response.write('\ufeff')  # BOM pour Excel FR

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Code', 'Bénéficiaire', 'Email', 'Statut', 'Utilisé le'])
    for c in codes:
        writer.writerow([
            c.code,
            c.beneficiary_name,
            c.beneficiary_email,
            'Utilisé' if c.used_at else 'Disponible',
            c.used_at.strftime('%d/%m/%Y %H:%M') if c.used_at else '',
        ])
    return response

def claim_free_ticket(request, slug):
    """
    Page PUBLIQUE : un bénéficiaire saisit son code gratuit et reçoit
    son billet.

    Flux (POST réussi) :
    1. Valide le code (existe, non utilisé, lié à cet événement)
    2. Crée une GuestOrder gratuite (total=0, PAID direct)
    3. Crée un GuestOrderItem (unit_price=0)
    4. Génère le GuestTicket
    5. Marque le code utilisé
    6. Log AuditLog FREE_TICKET_CLAIMED
    7. Redirige vers tickets:guest_confirmation (même template que l'achat normal)
    """
    from django.db import transaction
    from apps.tickets.models import (
        FreeTicketCode, GuestOrder, GuestOrderItem, GuestTicket,
    )
    from apps.dashboard.models import AuditLog
    from apps.dashboard.services import log_action

    event = get_object_or_404(
        Event,
        slug=slug,
        status=Event.Status.PUBLISHED,
    )

    # --- GET : affiche le formulaire ---
    if request.method == 'GET':
        return render(request, 'events/free_ticket_claim.html', {
            'event': event,
        })

    # --- POST : traite la réclamation ---
    raw_code = (request.POST.get('code') or '').strip().upper()

    if not raw_code:
        messages.error(request, "Veuillez saisir votre code.")
        return render(request, 'events/free_ticket_claim.html', {
            'event': event,
        })

    with transaction.atomic():
        # 1. Verrouille + valide le code
        code = (
            FreeTicketCode.objects
            .select_for_update()
            .filter(event=event, code=raw_code)
            .first()
        )

        if not code:
            messages.error(
                request,
                "Code introuvable pour cet événement. Vérifiez la saisie."
            )
            return render(request, 'events/free_ticket_claim.html', {
                'event': event,
            })

        if code.used_at is not None:
            messages.error(
                request,
                "Ce code a déjà été utilisé."
            )
            return render(request, 'events/free_ticket_claim.html', {
                'event': event,
            })

        # 2. Détermine le ticket_type (celui du code ou le 1er dispo)
        ticket_type = code.ticket_type
        if not ticket_type:
            ticket_type = event.ticket_types.order_by('order', 'price').first()
            if not ticket_type:
                messages.error(
                    request,
                    "Aucun type de billet disponible pour cet événement."
                )
                return render(request, 'events/free_ticket_claim.html', {
                    'event': event,
                })

        # 3. Split du nom bénéficiaire en first_name / last_name
        name_parts = code.beneficiary_name.strip().split(maxsplit=1)
        first_name = name_parts[0] if name_parts else 'Bénéficiaire'
        last_name  = name_parts[1] if len(name_parts) > 1 else ''

        # 4. Crée la GuestOrder gratuite (PAID direct)
        guest_order = GuestOrder.objects.create(
            first_name=first_name,
            last_name=last_name,
            email=code.beneficiary_email,
            phone='',
            subtotal=0,
            total=0,
            status=GuestOrder.Status.PAID,
            payment_method='free_code',
            payment_reference=code.code,
            paid_at=timezone.now(),
        )

        # 5. Crée la ligne de commande
        guest_item = GuestOrderItem.objects.create(
            order=guest_order,
            ticket_type=ticket_type,
            quantity=1,
            unit_price=0,
            subtotal=0,
        )

        # 6. Génère le GuestTicket
        guest_item.generate_tickets()
        ticket = GuestTicket.objects.filter(order_item=guest_item).first()

        # 7. Marque le code utilisé
        code.used_at = timezone.now()
        code.guest_ticket = ticket
        code.save(update_fields=['used_at', 'guest_ticket'])

        # 8. Log
        log_action(
            action=AuditLog.Action.FREE_TICKET_CLAIMED,
            description=(
                f"Billet gratuit réclamé pour « {event.title} » "
                f"(bénéficiaire : {code.beneficiary_name}, code {code.code})."
            ),
            user=None,
            model_name='GuestOrder',
            object_id=guest_order.order_number,
            metadata={
                'event_slug':    event.slug,
                'code':          code.code,
                'guest_order':   guest_order.order_number,
                'ticket_number': ticket.ticket_number if ticket else None,
            },
            ip_address=request.META.get('REMOTE_ADDR'),
        )

    # ✅ Envoi de l'email de confirmation au bénéficiaire — même flux
    # que pour un achat normal (voir guest_payment_return dans
    # apps/tickets/views.py). Hors transaction pour ne pas bloquer
    # l'enregistrement si le SMTP est lent.
    try:
        from apps.notifications.tasks import send_guest_ticket_email_async
        send_guest_ticket_email_async.delay(str(guest_order.uuid))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Échec envoi email billet gratuit {guest_order.order_number}: {e}"
        )

    messages.success(
        request,
        f"🎉 Votre billet gratuit est prêt ! Code {code.code} validé. "
        f"Un email de confirmation a été envoyé à {guest_order.email}."
    )
    return redirect(
        'tickets:guest_confirmation',
        access_token=str(guest_order.access_token),
    )