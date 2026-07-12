"""
IvoirPass V2 — Vues du Scanner QR Code
"""
from django_ratelimit.decorators import ratelimit
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from apps.events.models import Event
from apps.tickets.models import Ticket
from .models import ScanSession, ScanLog


def scanner_required(view_func):
    """Décorateur : réservé aux agents scanner et admins."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (
            request.user.is_scanner_agent or
            request.user.is_organizer or
            request.user.is_platform_admin
        ):
            messages.error(
                request,
                "Accès réservé aux agents de scan."
            )
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


@scanner_required
def scanner_index(request):
    """
    Page d'accueil du scanner.
    Liste les événements disponibles pour le scan.
    """
    user = request.user
    now  = timezone.now()

    # Événements disponibles selon le rôle
    if user.is_platform_admin:
        # Admin voit tous les événements publiés
        events = Event.objects.filter(
            status='published'
        ).order_by('start_date')
    elif user.is_organizer:
        # Organisateur voit ses propres événements
        events = Event.objects.filter(
            organizer=user,
            status='published'
        ).order_by('start_date')
    else:
        # Agent scanner : événements qui lui sont assignés
        # (utilise le champ scanner_agents de l'Event si défini,
        #  sinon tous les événements publiés pour simplifier)
        events = Event.objects.filter(
            status='published'
        ).order_by('start_date')

    # Sépare événements en cours / à venir
    ongoing  = events.filter(
        start_date__lte=now,
        end_date__gte=now
    )
    upcoming = events.filter(start_date__gt=now)[:10]
    past     = events.filter(end_date__lt=now)[:5]

    # Stats de scan du jour
    today_sessions = ScanSession.objects.filter(
        agent=user,
        started_at__date=now.date()
    )
    today_stats = {
        'sessions':  today_sessions.count(),
        'scanned':   sum(s.total_scanned  for s in today_sessions),
        'valid':     sum(s.total_valid    for s in today_sessions),
        'rejected':  sum(s.total_rejected for s in today_sessions),
    }

    return render(request, 'scanner/index.html', {
        'ongoing':     ongoing,
        'upcoming':    upcoming,
        'past':        past,
        'today_stats': today_stats,
    })


@scanner_required
def scan_event(request, event_id):
    """
    Interface principale de scan pour un événement.
    Page optimisée mobile avec caméra.
    """
    if request.user.is_platform_admin:
        event = get_object_or_404(Event, pk=event_id)
    else:
        event = get_object_or_404(Event, pk=event_id, organizer=request.user)

    # Crée ou récupère la session de scan du jour
    session, created = ScanSession.objects.get_or_create(
        agent=request.user,
        event=event,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()}
    )

    # Logs récents de cette session
    recent_logs = session.logs.select_related(
        'ticket__order_item__ticket_type'
    ).order_by('-scanned_at')[:20]

    return render(request, 'scanner/scan.html', {
        'event':       event,
        'session':     session,
        'recent_logs': recent_logs,
    })


@login_required
@require_POST
@ratelimit(key='user', rate='60/m', block=True)
def validate_qr(request):
    """
    API endpoint — Valide un QR Code scanné.

    POST /scanner/valider/
    Body JSON : { "qr_data": "...", "event_id": 123, "session_id": 456 }

    Returns JSON :
    {
        "result": "valid" | "already_used" | "invalid_qr" | ...,
        "message": "...",
        "ticket_info": { ... } | null,
        "color": "green" | "red" | "orange"
    }
    """
    try:
        body      = json.loads(request.body)
        qr_data   = body.get('qr_data', '').strip()
        event_id  = body.get('event_id')
        session_id = body.get('session_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({
            'result':  'invalid_qr',
            'message': 'Données invalides.',
            'color':   'red',
        }, status=400)

    # Récupère la session
    try:
        session = ScanSession.objects.get(
            pk=session_id,
            agent=request.user
        )
        event = session.event
    except ScanSession.DoesNotExist:
        return JsonResponse({
            'result':  'invalid_qr',
            'message': 'Session invalide.',
            'color':   'red',
        })

    # ============================================
    # VALIDATION DU QR CODE
    # ============================================
    ticket      = None
    result      = None
    message     = ''
    ticket_info = None

    # 1. Format du QR : uuid:ticket_number:signature
    parts = qr_data.split(':')
    if len(parts) < 4:
        result  = ScanLog.Result.INVALID_QR
        message = "QR Code invalide — format incorrect."
        color   = 'red'

    else:
        ticket_uuid   = parts[0]
        ticket_number = parts[1]

        # 2. Cherche le ticket — verrouillé en base (select_for_update) le temps
        # de la vérification et du marquage, pour qu'un second agent scannant
        # le MÊME billet à la même milliseconde attende son tour et voie bien
        # "déjà utilisé" au lieu de valider deux fois le même billet.
        with transaction.atomic():
            try:
                ticket = Ticket.objects.select_for_update().select_related(
                    'order_item__ticket_type__event',
                    'order_item__order__buyer'
                ).get(
                    uuid=ticket_uuid,
                    ticket_number=ticket_number
                )
            except Ticket.DoesNotExist:
                result  = ScanLog.Result.NOT_FOUND
                message = "Ticket introuvable dans notre système."
                color   = 'red'
                ticket  = None

            if ticket:
                # 3. Vérifie la signature HMAC
                if not ticket.verify_qr(qr_data):
                    result  = ScanLog.Result.INVALID_QR
                    message = "Signature QR invalide — billet falsifié."
                    color   = 'red'

                # 4. Vérifie que c'est le bon événement
                elif ticket.event.id != event.id:
                    result  = ScanLog.Result.WRONG_EVENT
                    message = (
                        f"Ce billet est pour : "
                        f"« {ticket.event.title} », "
                        f"pas cet événement."
                    )
                    color   = 'orange'

                # 5. Vérifie que le ticket n'est pas annulé
                elif ticket.status == Ticket.Status.VOID:
                    result  = ScanLog.Result.TICKET_VOID
                    message = "Ce billet a été annulé."
                    color   = 'red'

                # 6. Vérifie que le ticket n'est pas déjà utilisé
                elif ticket.status == Ticket.Status.USED:
                    result  = ScanLog.Result.ALREADY_USED
                    message = (
                        f"Billet déjà utilisé "
                        f"le {ticket.scanned_at.strftime('%d/%m/%Y à %H:%M')}."
                    )
                    color   = 'red'

                # 7. TICKET VALIDE ✅
                else:
                    result  = ScanLog.Result.VALID
                    message = "Accès autorisé ✅"
                    color   = 'green'

                    # Invalide le ticket — toujours dans la même transaction
                    # verrouillée, avant que quiconque d'autre ne puisse le relire.
                    ticket.mark_as_used(scanned_by=request.user)

                    ticket_info = {
                        'ticket_number': ticket.ticket_number,
                        'ticket_type':   ticket.ticket_type.name,
                        'buyer_name':    ticket.buyer.get_full_name(),
                        'buyer_email':   ticket.buyer.email,
                        'event_title':   ticket.event.title,
                    }

    # ============================================
    # ENREGISTREMENT DU LOG
    # ============================================
    ScanLog.objects.create(
        session          = session,
        ticket           = ticket,
        qr_data_received = qr_data[:500],
        result           = result,
    )

    # Mise à jour des compteurs de session
    session.total_scanned += 1
    if result == ScanLog.Result.VALID:
        session.total_valid += 1
    else:
        session.total_rejected += 1
    session.save(update_fields=[
        'total_scanned', 'total_valid', 'total_rejected'
    ])

    return JsonResponse({
        'result':      result,
        'message':     message,
        'color':       color,
        'ticket_info': ticket_info,
        'session': {
            'total_scanned':  session.total_scanned,
            'total_valid':    session.total_valid,
            'total_rejected': session.total_rejected,
        }
    })


@scanner_required
def scan_history(request, event_id):
    """Historique complet des scans pour un événement."""
    event = get_object_or_404(Event, pk=event_id)

    sessions = ScanSession.objects.filter(
        event=event,
        agent=request.user
    ).prefetch_related('logs').order_by('-started_at')

    all_logs = ScanLog.objects.filter(
        session__event=event,
        session__agent=request.user
    ).select_related(
        'ticket__order_item__ticket_type',
        'ticket__order_item__order__buyer'
    ).order_by('-scanned_at')[:100]

    # Stats globales
    stats = {
        'total':    all_logs.count(),
        'valid':    all_logs.filter(result='valid').count(),
        'rejected': all_logs.exclude(result='valid').count(),
    }

    return render(request, 'scanner/history.html', {
        'event':    event,
        'sessions': sessions,
        'logs':     all_logs,
        'stats':    stats,
    })


@scanner_required
def scanner_app(request):
    """
    Sert l'application PWA de scan (scanner_app/index.html) directement
    depuis le site — plus besoin de lancer un serveur local à part.
    Protégée par le même contrôle d'accès que le reste du scanner.
    """
    return render(request, 'scanner_app/index.html')