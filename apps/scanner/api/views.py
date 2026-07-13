"""
IvoirPass V2 — API Scan QR pour application mobile externe (scanner_app)

Authentification : JWT (même mécanisme que le reste de l'API IvoirPass).
Chaque agent se connecte avec son propre compte (email + mot de passe) via
/api/accounts/token/ pour obtenir un access token, puis l'envoie en en-tête
Authorization: Bearer <token> sur chaque appel à cette API.

Conçu pour plusieurs agents scannant SIMULTANÉMENT le même événement :
le ticket est verrouillé en base (select_for_update) le temps de la
vérification, pour qu'un même billet ne puisse jamais être validé deux fois
même si deux agents le scannent à la même milliseconde.
"""
import json
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from django_ratelimit.decorators import ratelimit
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.tickets.models import Ticket
from apps.events.models import Event
from apps.scanner.models import ScanSession, ScanLog


def _authenticate_agent(request):
    """Authentifie l'agent via JWT et vérifie son rôle."""
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
@api_view(['POST'])
@permission_classes([AllowAny])
def scan_qr_api(request):
    """
    Scanne un QR code depuis scanner_app.

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

    try:
        event = Event.objects.get(pk=event_id, status='published')
    except Event.DoesNotExist:
        return JsonResponse({'result': 'wrong_event', 'message': 'Événement introuvable'})

    if agent.is_organizer and not agent.is_platform_admin and event.organizer_id != agent.id:
        return JsonResponse(
            {'result': 'unauthorized', 'message': "Vous n'êtes pas l'organisateur de cet événement"},
            status=403,
        )

    session, _ = ScanSession.objects.get_or_create(
        event=event,
        agent=agent,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()}
    )

    parts = qr_data.split(':')
    ticket = None
    ticket_info = None

    if len(parts) < 4:
        result = ScanLog.Result.INVALID_QR
        message = "QR Code invalide"
        color = 'red'
    else:
        ticket_uuid = parts[0]
        ticket_number = parts[1]

        # Verrouillage en base le temps de la vérification + du marquage :
        # empêche deux agents de valider simultanément le même billet.
        with transaction.atomic():
            try:
                ticket = Ticket.objects.select_for_update().select_related(
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
                    ticket.mark_as_used(scanned_by=agent)

                    ticket_info = {
                        'ticket_number': ticket.ticket_number,
                        'ticket_type': ticket.order_item.ticket_type.name,
                        'buyer_name': ticket.order_item.order.buyer.get_full_name() if ticket.order_item.order.buyer else 'Invité',
                        'event_title': ticket.event.title,
                    }

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

    return JsonResponse({
        'result': result,
        'message': message,
        'color': color,
        'ticket_info': ticket_info,
    })
