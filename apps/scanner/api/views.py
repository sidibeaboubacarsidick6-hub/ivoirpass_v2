"""
IvoirPass V2 — API Scan QR

Authentification : session Django classique (cookie), la même que
l'agent utilise pour se connecter sur scanner_app via /accounts/login/.
Pas de clé API partagée — chaque scan est attribué au vrai agent connecté.
"""
import json
import uuid as uuid_lib

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from apps.tickets.models import Ticket
from apps.events.models import Event
from apps.scanner.models import ScanSession, ScanLog


def _check_agent(request):
    """Vérifie que l'utilisateur est connecté (session) et a le bon rôle."""
    user = request.user
    if not user.is_authenticated:
        return None, JsonResponse({'result': 'unauthorized', 'message': 'Session expirée, reconnectez-vous.'}, status=401)
    if not user.is_active:
        return None, JsonResponse({'result': 'unauthorized', 'message': 'Compte désactivé'}, status=403)
    if not (user.is_scanner_agent or user.is_organizer or user.is_platform_admin):
        return None, JsonResponse({'result': 'unauthorized', 'message': 'Rôle non autorisé à scanner'}, status=403)
    return user, None


@csrf_exempt
@require_POST
def scan_qr_api(request):
    """API pour scanner un QR code depuis scanner_app (session Django)."""

    agent, error_response = _check_agent(request)
    if error_response:
        return error_response

    try:
        body = json.loads(request.body)
        qr_data = body.get('qr_data', '').strip()
        event_id = body.get('event_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'result': 'invalid_qr', 'message': 'Données invalides'}, status=400)

    try:
        event = Event.objects.get(pk=event_id, status='published')
    except Event.DoesNotExist:
        return JsonResponse({'result': 'wrong_event', 'message': 'Événement introuvable'})

    # Un organisateur ne peut scanner que ses propres événements
    # (les agents scanner et admins plateforme peuvent scanner tout événement publié).
    if agent.is_organizer and not agent.is_platform_admin and event.organizer_id != agent.id:
        return JsonResponse(
            {'result': 'unauthorized', 'message': "Vous n'êtes pas l'organisateur de cet événement"},
            status=403,
        )

    session, _ = ScanSession.objects.get_or_create(
        event=event, agent=agent,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()}
    )

    parts = qr_data.split(':')
    ticket = None
    result = None
    message = ''
    color = 'red'

    if len(parts) < 4:
        result, message, color = ScanLog.Result.INVALID_QR, "QR Code invalide", 'red'
    else:
        ticket_uuid = parts[0]
        ticket_number = parts[1]

        # Valider le format UUID avant de requêter la base
        try:
            uuid_lib.UUID(ticket_uuid)
        except (ValueError, AttributeError):
            result, message, color = ScanLog.Result.INVALID_QR, "QR Code invalide", 'red'

        if result is None:
            # Verrouillage en base le temps de la vérification + du marquage :
            # empêche deux agents de valider simultanément le même billet.
            with transaction.atomic():
                try:
                    ticket = Ticket.objects.select_for_update().select_related(
                        'order_item__ticket_type__event', 'order_item__order__buyer'
                    ).get(uuid=ticket_uuid, ticket_number=ticket_number)
                except Ticket.DoesNotExist:
                    result, message, color = ScanLog.Result.NOT_FOUND, "Ticket introuvable", 'red'
                    ticket = None

                if ticket:
                    if not ticket.verify_qr(qr_data):
                        result, message, color = ScanLog.Result.INVALID_QR, "QR falsifié", 'red'
                    elif ticket.event.id != event.id:
                        result, message, color = ScanLog.Result.WRONG_EVENT, f"Ce billet est pour : {ticket.event.title}", 'orange'
                    elif ticket.status == Ticket.Status.VOID:
                        result, message, color = ScanLog.Result.TICKET_VOID, "Billet annulé", 'red'
                    elif ticket.status == Ticket.Status.USED:
                        result, message, color = ScanLog.Result.ALREADY_USED, f"Déjà utilisé le {ticket.scanned_at.strftime('%d/%m/%Y à %H:%M')}", 'red'
                    else:
                        result, message, color = ScanLog.Result.VALID, "Accès autorisé ✅", 'green'
                        ticket.mark_as_used(scanned_by=agent)

    ScanLog.objects.create(session=session, ticket=ticket, qr_data_received=qr_data[:500], result=result)

    session.total_scanned += 1
    if result == ScanLog.Result.VALID:
        session.total_valid += 1
    else:
        session.total_rejected += 1
    session.save(update_fields=['total_scanned', 'total_valid', 'total_rejected'])

    response_data = {'result': result, 'message': message, 'color': color}
    if ticket and result == ScanLog.Result.VALID:
        buyer = ticket.order_item.order.buyer if ticket.order_item.order.buyer else None
        response_data['ticket_info'] = {
            'ticket_number': ticket.ticket_number,
            'ticket_type': ticket.order_item.ticket_type.name,
            'buyer_name': buyer.get_full_name() if buyer else 'Invité',
            'event_title': ticket.event.title,
        }

    return JsonResponse(response_data)


@csrf_exempt
@require_POST
def check_event_exists(request):
    """Vérifie si un événement existe (pour l'app scanner)."""
    try:
        body = json.loads(request.body)
        event_id = body.get('event_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'exists': False})

    exists = Event.objects.filter(pk=event_id, status='published').exists()
    return JsonResponse({'exists': exists})