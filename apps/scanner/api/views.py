"""
IvoirPass V2 — API Scan QR pour application mobile externe
"""
import json
import hmac
import hashlib
from django_ratelimit.decorators import ratelimit
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from django.utils import timezone
from apps.tickets.models import Ticket
from apps.events.models import Event
from apps.scanner.models import ScanSession, ScanLog


@csrf_exempt
@require_POST
@ratelimit(key='ip', rate='30/m', block=True)
@permission_classes([AllowAny])
def scan_qr_api(request):
    """
    API publique pour scanner un QR code.
    Nécessite une clé API pour l'authentification.
    
    Headers:
        X-API-Key: <clé API du scanner>
    
    Body:
        qr_data: chaîne du QR code
        event_id: ID de l'événement
        agent_email: email de l'agent scanner (optionnel)
    
    Réponse:
        {
            "result": "valid" | "already_used" | "invalid_qr" | "wrong_event" | "not_found",
            "message": "...",
            "color": "green" | "red" | "orange",
            "ticket_info": { ... }
        }
    """
    # Vérifier la clé API — AUCUN fallback : si SCANNER_API_KEY n'est pas
    # configurée explicitement, l'API refuse tout appel plutôt que d'utiliser
    # une clé par défaut connue publiquement (ancien comportement dangereux).
    expected_key = getattr(settings, 'SCANNER_API_KEY', '') or ''
    api_key = request.headers.get('X-API-Key', '')

    if not expected_key:
        return JsonResponse(
            {'result': 'unauthorized', 'message': 'API scanner non configurée'}, status=503
        )
    if not api_key or not hmac.compare_digest(api_key, expected_key):
        return JsonResponse({'result': 'unauthorized', 'message': 'Clé API invalide'}, status=403)

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

    # Utiliser un utilisateur système pour l'API mobile
    from apps.accounts.models import CustomUser
    scanner_user, _ = CustomUser.objects.get_or_create(
        email='scanner-api@ivoirpass.com',
        defaults={
            'role': 'scanner',
            'is_active': True,
            'first_name': 'API',
            'last_name': 'Scanner'
        }
    )

    # Créer ou récupérer la session du jour
    session, _ = ScanSession.objects.get_or_create(
        event=event,
        agent=scanner_user,
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