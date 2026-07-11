"""
IvoirPass V2 — API Scan QR pour application mobile externe

Authentification : JWT (même mécanisme que le reste de l'API IvoirPass).
Chaque agent scanner se connecte avec son propre compte (email + mot de
passe) via /api/accounts/token/ pour obtenir un access token, puis l'envoie
en en-tête Authorization: Bearer <token> sur chaque appel à cette API.

Avantages par rapport à l'ancienne clé API partagée :
- Chaque scan est attribué au VRAI agent qui l'a effectué (traçabilité réelle
  dans ScanSession/ScanLog), plus à un compte système fictif partagé.
- Un agent désactivé (is_active=False) ou dont le rôle change perd l'accès
  immédiatement, sans avoir à faire tourner une clé partagée à tout le monde.
- Cohérent avec le reste de la plateforme (JWTAuthentication déjà utilisé
  partout ailleurs dans apps/accounts/api/views.py).
"""
import json

from django_ratelimit.decorators import ratelimit
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.tickets.models import Ticket
from apps.events.models import Event
from apps.scanner.models import ScanSession, ScanLog


def _authenticate_agent(request):
    """
    Authentifie l'agent via JWT et vérifie son rôle.
    Retourne (user, None) si OK, ou (None, JsonResponse d'erreur) sinon.
    """
    try:
        auth_result = JWTAuthentication().authenticate(request)
    except AuthenticationFailed as exc:
        return None, JsonResponse({'result': 'unauthorized', 'message': str(exc)}, status=401)

    if auth_result is None:
        return None, JsonResponse(
            {'result': 'unauthorized', 'message': 'Authentification requise (Authorization: Bearer <token>)'},
            status=401,
        )

    user, _token = auth_result

    if not user.is_active:
        return None, JsonResponse({'result': 'unauthorized', 'message': 'Compte désactivé'}, status=403)

    if not (user.is_scanner_agent or user.is_organizer or user.is_platform_admin):
        return None, JsonResponse(
            {'result': 'unauthorized', 'message': 'Rôle non autorisé à scanner'}, status=403
        )

    return user, None


@csrf_exempt
@require_POST
@ratelimit(key='ip', rate='60/m', block=True)
def scan_qr_api(request):
    """
    API pour scanner un QR code depuis l'application mobile externe.

    Headers:
        Authorization: Bearer <access_token JWT>

    Body:
        qr_data: chaîne du QR code
        event_id: ID de l'événement

    Réponse:
        {
            "result": "valid" | "already_used" | "invalid_qr" | "wrong_event" | "not_found",
            "message": "...",
            "color": "green" | "red" | "orange",
            "ticket_info": { ... }
        }
    """
    agent, error_response = _authenticate_agent(request)
    if error_response:
        return error_response

    try:
        body = json.loads(request.body)
        qr_data = body.get('qr_data', '').strip()
        event_id = body.get('event_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'result': 'invalid_qr', 'message': 'Données invalides'}, status=400)

    # Trouver l'événement
    try:
        event = Event.objects.get(pk=event_id, status='published')
    except Event.DoesNotExist:
        return JsonResponse({'result': 'wrong_event', 'message': 'Événement introuvable'})

    # Un organisateur ne peut scanner que ses propres événements.
    # Les agents scanner et les admins plateforme peuvent scanner tout événement publié
    # (même limitation que le scanner web — voir apps/scanner/views.py::scan_event).
    if agent.is_organizer and not agent.is_platform_admin and event.organizer_id != agent.id:
        return JsonResponse(
            {'result': 'unauthorized', 'message': "Vous n'êtes pas l'organisateur de cet événement"},
            status=403,
        )

    # Créer ou récupérer la session du jour, attribuée au VRAI agent connecté
    session, _ = ScanSession.objects.get_or_create(
        event=event,
        agent=agent,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()}
    )

    # Valider le QR code
    parts = qr_data.split(':')
    if len(parts) < 4:
        result = ScanLog.Result.INVALID_QR
        message = "QR Code invalide"
        color = 'red'
        ticket = None
    else:
        ticket_uuid = parts[0]
        ticket_number = parts[1]

        try:
            ticket = Ticket.objects.select_related(
                'order_item__ticket_type__event',
                'order_item__order__buyer'
            ).get(uuid=ticket_uuid, ticket_number=ticket_number)
        except Ticket.DoesNotExist:
            result = ScanLog.Result.NOT_FOUND
            message = "Ticket introuvable"
            color = 'red'
            ticket = None

        if ticket:
            if not ticket.verify_qr(qr_data):
                result = ScanLog.Result.INVALID_QR
                message = "QR falsifié"
                color = 'red'
            elif ticket.event.id != event.id:
                result = ScanLog.Result.WRONG_EVENT
                message = f"Ce billet est pour : {ticket.event.title}"
                color = 'orange'
            elif ticket.status == Ticket.Status.VOID:
                result = ScanLog.Result.TICKET_VOID
                message = "Billet annulé"
                color = 'red'
            elif ticket.status == Ticket.Status.USED:
                result = ScanLog.Result.ALREADY_USED
                message = f"Déjà utilisé le {ticket.scanned_at.strftime('%d/%m/%Y à %H:%M')}"
                color = 'red'
            else:
                result = ScanLog.Result.VALID
                message = "Accès autorisé ✅"
                color = 'green'
                ticket.mark_as_used()

    # Logger le scan
    ScanLog.objects.create(
        session=session,
        ticket=ticket,
        qr_data_received=qr_data[:500],
        result=result,
    )

    session.total_scanned += 1
    if result == ScanLog.Result.VALID:
        session.total_valid += 1
    else:
        session.total_rejected += 1
    session.save(update_fields=['total_scanned', 'total_valid', 'total_rejected'])

    # Réponse
    response_data = {
        'result': result,
        'message': message,
        'color': color,
    }

    if ticket and result == ScanLog.Result.VALID:
        buyer = ticket.order_item.order.buyer if ticket.order_item.order.buyer else None
        response_data['ticket_info'] = {
            'ticket_number': ticket.ticket_number,
            'ticket_type': ticket.order_item.ticket_type.name,
            'buyer_name': buyer.get_full_name() if buyer else 'Invité',
            'event_title': ticket.event.title,
        }

    return JsonResponse(response_data)
