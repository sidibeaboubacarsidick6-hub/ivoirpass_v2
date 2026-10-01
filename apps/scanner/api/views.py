"""
IvoirPass V2 — API Scan QR

Authentification : session Django classique (cookie), la même que
l'agent utilise pour se connecter sur scanner_app via /accounts/login/.
Pas de clé API partagée — chaque scan est attribué au vrai agent connecté.

Chantier B (2026-09-27) — Scanner PWA offline :
  - _process_scan() : logique unique réutilisée par online/offline
  - prepare_event_offline : pull des tickets pour cache local
  - sync_offline_scans : batch push de la queue offline avec idempotence
"""
import json
import uuid as uuid_lib

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction
from apps.tickets.models import Ticket, GuestTicket
from apps.events.models import Event
from apps.scanner.models import ScanSession, ScanLog
from apps.dashboard.models import AuditLog
from apps.dashboard.services import log_action


# ============================================================
# Auth & autorisation
# ============================================================

def _check_agent(request):
    """Vérifie que l'utilisateur est connecté (session) et a le bon rôle."""
    user = request.user
    if not user.is_authenticated:
        return None, JsonResponse(
            {'result': 'unauthorized', 'message': 'Session expirée, reconnectez-vous.'},
            status=401,
        )
    if not user.is_active:
        return None, JsonResponse(
            {'result': 'unauthorized', 'message': 'Compte désactivé'},
            status=403,
        )
    if not (user.is_scanner_agent or user.is_organizer or user.is_platform_admin):
        return None, JsonResponse(
            {'result': 'unauthorized', 'message': 'Rôle non autorisé à scanner'},
            status=403,
        )
    return user, None


def _authorize_agent_for_event(agent, event):
    """
    Vérifie que l'agent a le droit de scanner cet événement.
    Retourne None si OK, sinon un JsonResponse d'erreur.
    """
    if agent.is_platform_admin:
        return None
    if agent.is_organizer:
        if event.organizer_id != agent.id:
            return JsonResponse(
                {'result': 'unauthorized',
                 'message': "Vous n'êtes pas l'organisateur de cet événement"},
                status=403,
            )
        return None
    # Agent scanner : doit être assigné à cet événement
    if not event.scanner_agents.filter(pk=agent.id).exists():
        return JsonResponse(
            {'result': 'unauthorized',
             'message': "Vous n'êtes pas assigné à cet événement"},
            status=403,
        )
    return None


# ============================================================
# Logique de scan (factorisée)
# ============================================================

def _process_scan(agent, event, session, qr_data, client_uuid=None):
    """
    Traite UN scan (online ou offline, même logique).

    Args:
        agent: CustomUser qui scanne.
        event: Event cible.
        session: ScanSession courante.
        qr_data: chaîne QR brute.
        client_uuid: UUID client (offline) ou None (online direct).

    Returns:
        dict {result, message, color, ticket_info?}
    """
    parts = qr_data.split(':')
    ticket = None
    is_guest_ticket = False
    result = None
    message = ''
    color = 'red'
    current_event_day = None   # 🎯 Vague 4 : jour concerné (multi-jours)

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
                    # Un billet acheté sans compte (invité) vit dans GuestTicket.
                    try:
                        ticket = GuestTicket.objects.select_for_update().select_related(
                            'order_item__ticket_type__event', 'order_item__order'
                        ).get(uuid=ticket_uuid, ticket_number=ticket_number)
                        is_guest_ticket = True
                    except GuestTicket.DoesNotExist:
                        result, message, color = ScanLog.Result.NOT_FOUND, "Ticket introuvable", 'red'
                        ticket = None

                if ticket:
                    if not ticket.verify_qr(qr_data):
                        result, message, color = ScanLog.Result.INVALID_QR, "QR falsifié", 'red'
                    elif ticket.event.id != event.id:
                        result, message, color = (
                            ScanLog.Result.WRONG_EVENT,
                            f"Ce billet est pour : {ticket.event.title}",
                            'orange',
                        )
                    else:
                        # 🎯 Vague 4 : logique multi-jours unifiée
                        today = timezone.now().date()
                        ok, reason, day = ticket.can_be_scanned_on(today)

                        if not ok:
                            if "annulé" in reason.lower():
                                result, message, color = ScanLog.Result.TICKET_VOID, reason, 'red'
                            elif "pas valide aujourd'hui" in reason.lower():
                                result, message, color = ScanLog.Result.WRONG_EVENT, reason, 'orange'
                            else:
                                result, message, color = ScanLog.Result.ALREADY_USED, reason, 'red'
                        else:
                            # Vérif : déjà scanné CE JOUR (multi-jours)
                            existing_today = None
                            if day:
                                qs = ScanLog.objects.filter(
                                    event_day=day,
                                    result=ScanLog.Result.VALID,
                                )
                                if is_guest_ticket:
                                    qs = qs.filter(guest_ticket=ticket)
                                else:
                                    qs = qs.filter(ticket=ticket)
                                existing_today = qs.order_by('-scanned_at').first()

                            if existing_today:
                                result, message, color = ScanLog.Result.ALREADY_USED, (
                                    f"Déjà scanné aujourd'hui à "
                                    f"{existing_today.scanned_at.strftime('%H:%M')}"
                                ), 'red'
                            else:
                                result, message, color = ScanLog.Result.VALID, "Accès autorisé ✅", 'green'
                                current_event_day = day

                                # Multi-jours : ne pas passer en USED
                                if day:
                                    if not ticket.scanned_at:
                                        ticket.scanned_at = timezone.now()
                                        ticket.save(update_fields=['scanned_at'])
                                else:
                                    if is_guest_ticket:
                                        ticket.mark_as_used()
                                    else:
                                        ticket.mark_as_used(scanned_by=agent)

    # Enregistrement du log (Vague 4 : + guest_ticket + event_day)
    ScanLog.objects.create(
        session=session,
        ticket=(ticket if ticket and not is_guest_ticket else None),
        guest_ticket=(ticket if ticket and is_guest_ticket else None),
        event_day=current_event_day,
        qr_data_received=qr_data[:500],
        result=result,
        client_uuid=client_uuid,
    )

    log_action(
        action=AuditLog.Action.TICKET_SCANNED,
        description=(
            f"Scan billet {ticket.ticket_number if ticket else qr_data[:30]} "
            f"— {result} — {event.title}"
        ),
        user=agent,
        model_name='GuestTicket' if is_guest_ticket else 'Ticket',
        object_id=ticket.ticket_number if ticket else '',
        metadata={'result': result, 'event': event.title},
    )

    session.total_scanned += 1
    if result == ScanLog.Result.VALID:
        session.total_valid += 1
    else:
        session.total_rejected += 1
    session.save(update_fields=['total_scanned', 'total_valid', 'total_rejected'])

    response_data = {'result': result, 'message': message, 'color': color}
    if ticket and result == ScanLog.Result.VALID:
        if is_guest_ticket:
            buyer_name = (
                f"{ticket.order_item.order.first_name} "
                f"{ticket.order_item.order.last_name}"
            )
        else:
            buyer = ticket.order_item.order.buyer if ticket.order_item.order.buyer else None
            buyer_name = buyer.get_full_name() if buyer else 'Invité'
        response_data['ticket_info'] = {
            'ticket_number': ticket.ticket_number,
            'ticket_type': ticket.order_item.ticket_type.name,
            'buyer_name': buyer_name,
            'event_title': ticket.event.title,
            'event_day': current_event_day.display_name if current_event_day else None,
        }

    return response_data


# ============================================================
# Endpoint online (existant, refactoré)
# ============================================================

@require_POST
def scan_qr_api(request):
    """
    API pour scanner un QR code depuis scanner_app (session Django).
    Comportement strictement identique à avant le refactor B-2b.
    """
    agent, error_response = _check_agent(request)
    if error_response:
        return error_response

    try:
        body = json.loads(request.body)
        qr_data = body.get('qr_data', '').strip()
        event_id = body.get('event_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse(
            {'result': 'invalid_qr', 'message': 'Données invalides'},
            status=400,
        )

    try:
        event = Event.objects.get(pk=event_id, status='published')
    except Event.DoesNotExist:
        return JsonResponse({'result': 'wrong_event', 'message': 'Événement introuvable'})

    err = _authorize_agent_for_event(agent, event)
    if err:
        return err

    session, _ = ScanSession.objects.get_or_create(
        event=event, agent=agent,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()},
    )

    return JsonResponse(_process_scan(agent, event, session, qr_data))


# ============================================================
# Chantier B — Endpoints offline
# ============================================================

@require_POST
def prepare_event_offline(request, event_id):
    """
    Renvoie la liste des billets de l'événement pour stockage local
    (IndexedDB) côté scanner PWA.

    Inclut VALID + USED + VOID :
      - VALID → autorisé localement
      - USED  → refusé localement sans round-trip
      - VOID  → refusé localement (billet annulé)

    Auth : même _check_agent + _authorize_agent_for_event.
    """
    agent, error_response = _check_agent(request)
    if error_response:
        return error_response

    try:
        event = Event.objects.get(pk=event_id, status='published')
    except Event.DoesNotExist:
        return JsonResponse(
            {'error': 'event_not_found', 'message': 'Événement introuvable'},
            status=404,
        )

    err = _authorize_agent_for_event(agent, event)
    if err:
        return err

    tickets = []

    # Billets "avec compte"
    account_tickets = (
        Ticket.objects
        .filter(order_item__ticket_type__event=event)
        .select_related('order_item__ticket_type', 'order_item__order__buyer')
    )
    for t in account_tickets:
        buyer = t.order_item.order.buyer
        tickets.append({
            'kind': 'account',
            'uuid': str(t.uuid),
            'ticket_number': t.ticket_number,
            'ticket_type': t.order_item.ticket_type.name,
            'buyer_name': buyer.get_full_name() if buyer else 'Invité',
            'qr_data': t.qr_code_data,
            'status': t.status,  # 'valid' | 'used' | 'void' | 'expired'
        })

    # Billets "invité"
    guest_tickets = (
        GuestTicket.objects
        .filter(order_item__ticket_type__event=event)
        .select_related('order_item__ticket_type', 'order_item__order')
    )
    for t in guest_tickets:
        order = t.order_item.order
        tickets.append({
            'kind': 'guest',
            'uuid': str(t.uuid),
            'ticket_number': t.ticket_number,
            'ticket_type': t.order_item.ticket_type.name,
            'buyer_name': f"{order.first_name} {order.last_name}",
            'qr_data': t.qr_code_data,
            'status': t.status,
        })

    return JsonResponse({
        'event_id': event.id,
        'event_title': event.title,
        'generated_at': timezone.now().isoformat(),
        'tickets': tickets,
    })


@require_POST
def sync_offline_scans(request):
    """
    Reçoit une queue de scans offline et les traite en batch.

    Body :
        {
          "event_id": 5,
          "scans": [
            {"client_uuid": "...", "qr_data": "..."},
            ...
          ]
        }

    Réponse :
        {
          "results": [
            {"client_uuid": "...", "result": "...", "message": "...", "color": "..."},
            ...
          ],
          "session_totals": {"total_scanned": N, "total_valid": M, "total_rejected": K}
        }

    Idempotence : si un `client_uuid` a déjà été traité pour cette session,
    on renvoie le résultat original sans créer de nouvelle ligne.
    """
    agent, error_response = _check_agent(request)
    if error_response:
        return error_response

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    event_id = body.get('event_id')
    scans = body.get('scans', [])

    if not isinstance(scans, list):
        return JsonResponse({'error': 'scans doit être une liste'}, status=400)

    # Limite défensive : 500 scans max par batch (le client découpe).
    if len(scans) > 500:
        return JsonResponse(
            {'error': 'batch_too_large', 'message': 'Maximum 500 scans par batch'},
            status=400,
        )

    try:
        event = Event.objects.get(pk=event_id, status='published')
    except Event.DoesNotExist:
        return JsonResponse(
            {'error': 'event_not_found', 'message': 'Événement introuvable'},
            status=404,
        )

    err = _authorize_agent_for_event(agent, event)
    if err:
        return err

    session, _ = ScanSession.objects.get_or_create(
        event=event, agent=agent,
        started_at__date=timezone.now().date(),
        defaults={'started_at': timezone.now()},
    )

    results = []

    for scan in scans:
        client_uuid_raw = scan.get('client_uuid', '').strip()
        qr_data = scan.get('qr_data', '').strip()

        # Valider le client_uuid (peut être absent → on process comme online)
        client_uuid = None
        if client_uuid_raw:
            try:
                client_uuid = uuid_lib.UUID(client_uuid_raw)
            except (ValueError, AttributeError):
                results.append({
                    'client_uuid': client_uuid_raw,
                    'result': 'invalid_qr',
                    'message': 'Identifiant client invalide',
                    'color': 'red',
                })
                continue

        # ── Idempotence : si ce client_uuid est déjà traité → renvoyer ───
        if client_uuid:
            existing = ScanLog.objects.filter(
                session=session, client_uuid=client_uuid,
            ).first()
            if existing:
                results.append({
                    'client_uuid': client_uuid_raw,
                    'result': existing.result,
                    'message': 'Déjà synchronisé',
                    'color': 'green' if existing.result == ScanLog.Result.VALID else 'red',
                    'idempotent': True,
                })
                continue

        # ── Traitement normal ────────────────────────────────────────────
        result_data = _process_scan(
            agent, event, session, qr_data, client_uuid=client_uuid,
        )
        results.append({
            'client_uuid': client_uuid_raw,
            'result': result_data['result'],
            'message': result_data['message'],
            'color': result_data['color'],
        })

    return JsonResponse({
        'results': results,
        'session_totals': {
            'total_scanned': session.total_scanned,
            'total_valid': session.total_valid,
            'total_rejected': session.total_rejected,
        },
    })



# ============================================================
# Endpoint utilitaire (conservé tel quel)
# ============================================================

@require_POST
def check_event_exists(request):
    """
    Vérifie si un événement existe (pour l'app scanner).

    Authentifié par cookie de session, même remarque que scan_qr_api :
    protection CSRF standard réactivée, jeton envoyé par le front-end.
    """
    agent, error_response = _check_agent(request)
    if error_response:
        return error_response

    try:
        body = json.loads(request.body)
        event_id = body.get('event_id')
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'exists': False})

    exists = Event.objects.filter(pk=event_id, status='published').exists()
    return JsonResponse({'exists': exists})