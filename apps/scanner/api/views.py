"""
IvoirPass V2 — API Scan QR
"""
import json
import hmac
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from apps.tickets.models import Ticket
from apps.events.models import Event
from apps.scanner.models import ScanSession, ScanLog
from apps.accounts.models import CustomUser


@csrf_exempt
@require_POST
def scan_qr_api(request):
    """API publique pour scanner un QR code. Authentification par clé API."""
    
    api_key = request.headers.get('X-API-Key', '')
    expected_key = getattr(settings, 'SCANNER_API_KEY', 'ivoirpass-scanner-2026')

    if not hmac.compare_digest(api_key, expected_key):
        return JsonResponse({'result': 'unauthorized', 'message': 'Clé API invalide'}, status=403)

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

    scanner_user, _ = CustomUser.objects.get_or_create(
        email='scanner-api@ivoirpass.com',
        defaults={'role': 'scanner', 'is_active': True, 'first_name': 'API', 'last_name': 'Scanner'}
    )

    session, _ = ScanSession.objects.get_or_create(
        event=event, agent=scanner_user,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()}
    )

    parts = qr_data.split(':')
    if len(parts) < 4:
        result, message, color = ScanLog.Result.INVALID_QR, "QR Code invalide", 'red'
        ticket = None
    else:
        ticket_uuid = parts[0]
        ticket_number = parts[1]
        try:
            ticket = Ticket.objects.select_related(
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
                ticket.mark_as_used()

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