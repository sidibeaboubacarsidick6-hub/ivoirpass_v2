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
from django.db.models import Q
from apps.events.models import Event
from apps.tickets.models import Ticket, GuestTicket
from .models import ScanSession, ScanLog


def scanner_required(view_func):
    """Décorateur : réservé aux agents scanner, organisateurs et admins."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (
            request.user.is_scanner_agent or
            request.user.is_organizer or
            request.user.is_platform_admin
        ):
            messages.error(request, "Accès réservé aux agents de scan.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


@scanner_required
def scanner_index(request):
    """Page d'accueil du scanner. Liste les événements disponibles pour le scan."""
    user = request.user
    now  = timezone.now()

    if user.is_platform_admin:
        events = Event.objects.filter(status='published').order_by('start_date')
    elif user.is_organizer:
        events = Event.objects.filter(organizer=user, status='published').order_by('start_date')
    else:
        # Agent scanner : uniquement les événements auxquels il a été
        # explicitement assigné par l'organisateur (voir Event.scanner_agents),
        # plus les événements de son propre compte s'il en organise aussi.
        events = Event.objects.filter(
            Q(scanner_agents=user) | Q(organizer=user),
            status='published',
        ).distinct().order_by('start_date')

    ongoing  = events.filter(start_date__lte=now, end_date__gte=now)
    upcoming = events.filter(start_date__gt=now)[:10]
    past     = events.filter(end_date__lt=now)[:5]

    today_sessions = ScanSession.objects.filter(agent=user, started_at__date=now.date())
    today_stats = {
        'sessions':  today_sessions.count(),
        'scanned':   sum(s.total_scanned  for s in today_sessions),
        'valid':     sum(s.total_valid    for s in today_sessions),
        'rejected':  sum(s.total_rejected for s in today_sessions),
    }

    return render(request, 'scanner/index.html', {
        'ongoing': ongoing, 'upcoming': upcoming, 'past': past, 'today_stats': today_stats,
    })


@scanner_required
def scan_event(request, event_id):
    """Interface principale de scan pour un événement."""
    if request.user.is_platform_admin:
        event = get_object_or_404(Event, pk=event_id)
    elif request.user.is_organizer:
        event = get_object_or_404(Event, pk=event_id, organizer=request.user)
    else:
        # Agent scanner : uniquement s'il a été explicitement assigné à
        # cet événement par l'organisateur.
        event = get_object_or_404(
            Event.objects.filter(Q(scanner_agents=request.user) | Q(organizer=request.user)),
            pk=event_id,
        )

    session, _ = ScanSession.objects.get_or_create(
        agent=request.user, event=event,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()}
    )

    recent_logs = session.logs.select_related(
        'ticket__order_item__ticket_type'
    ).order_by('-scanned_at')[:20]

    return render(request, 'scanner/scan.html', {
        'event': event, 'session': session, 'recent_logs': recent_logs,
    })


@login_required
@require_POST
@ratelimit(key='user', rate='60/m', block=True)
def validate_qr(request):
    """API endpoint — Valide un QR Code scanné."""
    try:
        body       = json.loads(request.body)
        qr_data    = body.get('qr_data', '').strip()
        event_id   = body.get('event_id')
        session_id = body.get('session_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'result': 'invalid_qr', 'message': 'Données invalides.', 'color': 'red'}, status=400)

    try:
        session = ScanSession.objects.get(pk=session_id, agent=request.user)
        event = session.event
    except ScanSession.DoesNotExist:
        return JsonResponse({'result': 'invalid_qr', 'message': 'Session invalide.', 'color': 'red'})

    ticket = None
    result = None
    message = ''
    ticket_info = None

    parts = qr_data.split(':')
    if len(parts) < 4:
        result, message, color = ScanLog.Result.INVALID_QR, "QR Code invalide — format incorrect.", 'red'
    else:
        ticket_uuid = parts[0]
        ticket_number = parts[1]

        with transaction.atomic():
            # Un billet peut appartenir à un compte normal (Ticket) OU avoir
            # été acheté sans compte (GuestTicket) — il faut chercher dans
            # les deux, sinon tout billet "invité" est signalé introuvable
            # alors qu'il est parfaitement valide.
            is_guest_ticket = False
            try:
                ticket = Ticket.objects.select_for_update().select_related(
                    'order_item__ticket_type__event', 'order_item__order__buyer'
                ).get(uuid=ticket_uuid, ticket_number=ticket_number)
            except Ticket.DoesNotExist:
                try:
                    ticket = GuestTicket.objects.select_for_update().select_related(
                        'order_item__ticket_type__event', 'order_item__order'
                    ).get(uuid=ticket_uuid, ticket_number=ticket_number)
                    is_guest_ticket = True
                except GuestTicket.DoesNotExist:
                    result, message, color = ScanLog.Result.NOT_FOUND, "Ticket introuvable.", 'red'

            if ticket:
                if not ticket.verify_qr(qr_data):
                    result, message, color = ScanLog.Result.INVALID_QR, "QR falsifié.", 'red'
                elif ticket.event.id != event.id:
                    result, message, color = ScanLog.Result.WRONG_EVENT, f"Billet pour : {ticket.event.title}", 'orange'
                elif ticket.status == 'void':
                    result, message, color = ScanLog.Result.TICKET_VOID, "Billet annulé.", 'red'
                elif ticket.status == 'used':
                    result, message, color = ScanLog.Result.ALREADY_USED, f"Déjà utilisé le {ticket.scanned_at.strftime('%d/%m/%Y à %H:%M')}.", 'red'
                else:
                    result, message, color = ScanLog.Result.VALID, "Accès autorisé ✅", 'green'
                    if is_guest_ticket:
                        ticket.mark_as_used()  # GuestTicket n'a pas de champ scanned_by (pas de compte)
                        buyer_name = f"{ticket.order_item.order.first_name} {ticket.order_item.order.last_name}"
                        buyer_email = ticket.order_item.order.email
                    else:
                        ticket.mark_as_used(scanned_by=request.user)
                        buyer_name = ticket.buyer.get_full_name()
                        buyer_email = ticket.buyer.email
                    ticket_info = {
                        'ticket_number': ticket.ticket_number,
                        'ticket_type':   ticket.ticket_type.name,
                        'buyer_name':    buyer_name,
                        'buyer_email':   buyer_email,
                        'event_title':   ticket.event.title,
                    }

    # ScanLog.ticket ne référence que le modèle Ticket (comptes normaux) —
    # pour un GuestTicket, on ne lie pas cette ligne à un ticket précis,
    # mais le scan est bien validé/enregistré dans les compteurs de session.
    ScanLog.objects.create(
        session=session,
        ticket=(ticket if ticket and not is_guest_ticket else None),
        qr_data_received=qr_data[:500],
        result=result,
    )

    session.total_scanned += 1
    if result == ScanLog.Result.VALID:
        session.total_valid += 1
    else:
        session.total_rejected += 1
    session.save(update_fields=['total_scanned', 'total_valid', 'total_rejected'])

    return JsonResponse({
        'result': result, 'message': message, 'color': color,
        'ticket_info': ticket_info,
        'session': {
            'total_scanned': session.total_scanned,
            'total_valid': session.total_valid,
            'total_rejected': session.total_rejected,
        }
    })


@scanner_required
def scan_history(request, event_id):
    """Historique complet des scans pour un événement."""
    event = get_object_or_404(Event, pk=event_id)

    sessions = ScanSession.objects.filter(
        event=event, agent=request.user
    ).prefetch_related('logs').order_by('-started_at')

    all_logs = ScanLog.objects.filter(
        session__event=event, session__agent=request.user
    ).select_related(
        'ticket__order_item__ticket_type', 'ticket__order_item__order__buyer'
    ).order_by('-scanned_at')

    stats = {
        'total':    all_logs.count(),
        'valid':    all_logs.filter(result='valid').count(),
        'rejected': all_logs.exclude(result='valid').count(),
    }

    all_logs = all_logs[:100]

    return render(request, 'scanner/history.html', {
        'event': event, 'sessions': sessions, 'logs': all_logs, 'stats': stats,
    })


def scanner_app(request):
    """
    Sert l'application PWA de scan (scanner_app/index.html).
    L'authentification est gérée par le template lui-même (login intégré).
    Aucune redirection Django — le template vérifie la session.
    """
    return render(request, 'scanner_app/index.html')