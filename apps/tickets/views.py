"""
IvoirPass V2 — Vues billetterie
"""
from django.shortcuts import render, redirect, get_object_or_404
import logging

logger = logging.getLogger(__name__)

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction

from apps.events.models import Event, TicketType
from apps.dashboard.models import AuditLog
from apps.dashboard.services import log_action, get_client_ip

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


# ============================================
# ✅ CORRECTIF AUDIT — H-3 : suppression du code mort
# ============================================

def cart_view(request):
    return redirect('home')


@login_required
def checkout(request):
    return redirect('home')


def order_confirmation(request, order_number):
    return redirect('home')


# ============================================
# GUEST CHECKOUT
# ============================================

def guest_checkout(request, slug):
    from .models import GuestOrder, GuestOrderItem

    event = get_object_or_404(Event, slug=slug, status='published')
    ticket_types = event.ticket_types.filter(is_visible=True).order_by('order', 'price')

    # 🔒 Vérification serveur : la vente doit être ouverte.
    if not event.is_on_sale:
        messages.error(
            request,
            "❌ Les ventes pour cet événement ne sont pas (ou plus) ouvertes."
        )
        return redirect('events:detail', slug=event.slug)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()

        selected_items = []
        total = 0
        for tt in ticket_types:
            qty = int(request.POST.get(f'quantity_{tt.pk}', 0))
            if qty > 0 and qty <= tt.max_per_order:
                subtotal = tt.price * qty
                total += subtotal
                selected_items.append({
                    'ticket_type': tt, 'quantity': qty,
                    'unit_price': tt.price, 'subtotal': subtotal,
                })

        errors = []
        if not first_name: errors.append("Le prénom est requis.")
        if not last_name: errors.append("Le nom est requis.")
        if not email: errors.append("L'email est requis.")
        if not selected_items: errors.append("Sélectionnez au moins un billet.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'tickets/guest_checkout.html', {
                'event': event, 'ticket_types': ticket_types,
            })

        order = GuestOrder.objects.create(
            first_name=first_name, last_name=last_name, email=email, phone=phone,
            subtotal=total, total=total, status=GuestOrder.Status.PENDING,
        )

        # Verrouillage : empêche la survente en cas de concurrence.
        with transaction.atomic():
            locked_types = {
                item['ticket_type'].pk: TicketType.objects.select_for_update().select_related('event').get(pk=item['ticket_type'].pk)
                for item in selected_items
            }

            for item in selected_items:
                tt_locked = locked_types[item['ticket_type'].pk]
                if tt_locked.quantity > 0 and tt_locked.quantity_sold + item['quantity'] > tt_locked.quantity:
                    order.delete()
                    messages.error(
                        request,
                        f"Stock insuffisant pour « {tt_locked.name} » — "
                        f"il ne reste que {max(0, tt_locked.quantity - tt_locked.quantity_sold)} billet(s)."
                    )
                    return render(request, 'tickets/guest_checkout.html', {
                        'event': event, 'ticket_types': ticket_types,
                    })

            for item in selected_items:
                GuestOrderItem.objects.create(
                    order=order, ticket_type=item['ticket_type'],
                    quantity=item['quantity'], unit_price=item['unit_price'],
                )
                tt = locked_types[item['ticket_type'].pk]
                tt.quantity_sold += item['quantity']
                tt.event.tickets_sold += item['quantity']
                tt.save(update_fields=['quantity_sold'])
                tt.event.save(update_fields=['tickets_sold'])

        log_action(
            action=AuditLog.Action.ORDER_CREATED,
            description=f"Commande invité {order.order_number} créée ({email})",
            obj=order,
            metadata={'total': str(total), 'email': email},
            ip_address=get_client_ip(request),
        )

        # ✅ IDOR fix : on redirige avec access_token, pas order_number
        return redirect('tickets:guest_payment', access_token=order.access_token)

    return render(request, 'tickets/guest_checkout.html', {
        'event': event, 'ticket_types': ticket_types,
    })


def guest_payment_initiate(request, access_token):
    """Initie le paiement pour une commande invité — provider piloté par .env."""
    from .models import GuestOrder
    from apps.payments.models import Payment
    from apps.payments.provider import get_payment_service, get_provider_name

    order = get_object_or_404(GuestOrder, access_token=access_token)

    if order.status == GuestOrder.Status.PAID:
        return redirect('tickets:guest_confirmation', access_token=access_token)

    current_provider = get_provider_name()
    payment, _created = Payment.objects.get_or_create(
        guest_order=order,
        defaults={
            'amount':   order.total,
            'provider': current_provider,
        },
    )
    # Si on change de provider ou si le paiement n'est plus pending → reset
    updates = []
    if payment.provider != current_provider:
        payment.provider = current_provider
        payment.provider_reference = ''   # nouvelle tentative → nouvelle ref
        updates += ['provider', 'provider_reference']
    if payment.status != Payment.Status.PENDING:
        payment.status = Payment.Status.PENDING
        updates.append('status')
    if payment.amount != order.total:
        payment.amount = order.total
        updates.append('amount')
    if updates:
        payment.save(update_fields=updates)

        # Récupérer l'opérateur choisi par le client (?network=wave_ci)
    selected_network = request.GET.get('network', None)
    
    service = get_payment_service()
    # Au lieu de : result = service.create_guest_invoice(order, request)
    result = service.create_guest_invoice(order, request, network=selected_network)

    if result['success']:
        payment.provider_reference = result['provider_reference']
        payment.raw_response = result['raw']
        payment.save(update_fields=['provider_reference', 'raw_response'])

        # Compat legacy : order.payment_reference pour les autres vues
        order.payment_reference = result['provider_reference']
        order.save(update_fields=['payment_reference'])

        logger.info("Initiation %s — Commande: %s, URL: %s",
                    current_provider, order.order_number,
                    result.get('payment_url') or '(aucune)')
        log_action(
            action=AuditLog.Action.PAYMENT_INITIATED,
            description=f"Paiement initié pour {order.order_number} via {current_provider}",
            user=request.user if request.user.is_authenticated else None,
            model_name='Payment', object_id=order.order_number,
            metadata={'amount': str(payment.amount), 'provider': current_provider},
            ip_address=get_client_ip(request),
        )

        # 🛡️ Défensif : si le provider renvoie déjà SUCCESSFUL (cas sandbox 00),
        # on confirme immédiatement sans attendre le webhook.
        raw_status = (result.get('raw', {}).get('status') or '').upper()
        if raw_status == 'SUCCESSFUL':
            newly_paid = order.mark_as_paid(
                payment_method=current_provider,
                payment_reference=result['provider_reference'],
            )
            if newly_paid:
                Payment.objects.filter(guest_order=order).update(
                    status=Payment.Status.COMPLETED,
                    completed_at=timezone.now(),
                    raw_response=result['raw'],
                )
                log_action(
                    action=AuditLog.Action.PAYMENT_SUCCESS,
                    description=f"Paiement confirmé immédiatement ({current_provider}) {order.order_number}",
                    model_name='Payment', object_id=order.order_number,
                    metadata={'provider': current_provider, 'amount': str(order.total)},
                    ip_address=get_client_ip(request),
                )
                from apps.notifications.tasks import send_guest_ticket_email_async
                send_guest_ticket_email_async.delay(str(order.uuid))
                messages.success(request, "🎉 Paiement confirmé ! Vos billets arrivent.")
                return redirect('tickets:guest_confirmation', access_token=order.access_token)

        # Provider avec page de paiement hébergée (PayDunya) → on redirige.
        # Provider push-USSD (FeexPay) → payment_url vide ou placeholder
        # sandbox, on renvoie vers la page de confirmation. Le webhook
        # confirmera le paiement.
        payment_url = (result.get('payment_url') or '').strip()
        if payment_url and not payment_url.startswith('https://sandbox-'):
            return redirect(payment_url)

        messages.info(
            request,
            "📱 Vérifiez votre téléphone pour valider le paiement. "
            "Vos billets vous seront envoyés dès confirmation.",
        )
        return redirect(
            'tickets:guest_confirmation', access_token=order.access_token,
        )

    # Échec
    payment.status = Payment.Status.FAILED
    payment.raw_response = result.get('raw', {})
    payment.save(update_fields=['status', 'raw_response'])
    log_action(
        action=AuditLog.Action.PAYMENT_FAILED,
        description=f"Échec initiation paiement {order.order_number}",
        model_name='Payment', object_id=order.order_number,
        metadata={'provider': current_provider,
                  'reason': str(result.get('error', ''))[:200]},
        ip_address=get_client_ip(request),
    )
    messages.error(request, f"Impossible d'initier le paiement : {result['error']}")
    first_item = order.guest_items.select_related('ticket_type__event').first()
    if first_item:
        return redirect('events:detail', slug=first_item.ticket_type.event.slug)
    return redirect('home')


def guest_payment_return(request, access_token):
    """Retour après paiement PayDunya — commande invité."""
    from .models import GuestOrder
    from apps.payments.provider import get_payment_service

    order = get_object_or_404(GuestOrder, access_token=access_token)

    if order.status == GuestOrder.Status.PAID:
        messages.success(request, "🎉 Votre paiement a été confirmé !")
        return redirect('tickets:guest_confirmation', access_token=access_token)

    token = request.GET.get('token', '').strip() or order.payment_reference or ''

    if token:
        result = get_payment_service().verify_payment(token)

        if result.get('success') and result.get('status') == 'completed':
            if order.is_payment_cancelled():
                messages.error(
                    request,
                    "❌ Votre paiement avait été annulé. Il ne peut pas être "
                    "relancé dans les 2 heures. Veuillez contacter le support."
                )
                return redirect('tickets:guest_confirmation', access_token=access_token)

            newly_confirmed = order.mark_as_paid(
                payment_method='paydunya', payment_reference=token,
            )
            if newly_confirmed:
                from apps.payments.models import Payment
                Payment.objects.filter(guest_order=order).update(
                    status=Payment.Status.COMPLETED,
                    completed_at=timezone.now(),
                    raw_response=result,
                )
                log_action(
                    action=AuditLog.Action.PAYMENT_SUCCESS,
                    description=f"Paiement confirmé (retour) pour la commande invité {order.order_number}",
                    model_name='Payment', object_id=order.order_number,
                    metadata={'provider': 'paydunya', 'amount': str(order.total)},
                    ip_address=get_client_ip(request),
                )
                from apps.notifications.tasks import send_guest_ticket_email_async
                send_guest_ticket_email_async.delay(str(order.uuid))
            messages.success(request, "🎉 Paiement confirmé !")
            return redirect('tickets:guest_confirmation', access_token=access_token)

    messages.info(request, "⏳ Vérification du paiement en cours...")
    return redirect('tickets:guest_confirmation', access_token=access_token)


def short_ticket_redirect(request, access_token):
    """
    URL courte utilisée dans les SMS : /b/<uuid>/

    Essaie d'abord de trouver une GuestOrder par access_token (cas
    standard — tous les achats invités passent par là). Si non trouvé,
    essaie une Order par uuid (achats avec compte — flux legacy).

    Le uuid d'Order n'est pas exposé ailleurs publiquement, il sert
    donc de token d'accès dans ce contexte.
    """
    from .models import GuestOrder, Order

    # Cas 1 : GuestOrder (cas réel en production — tous les achats
    # invités passent par ce modèle)
    try:
        order = GuestOrder.objects.get(access_token=access_token)
        return redirect('tickets:guest_confirmation', access_token=access_token)
    except GuestOrder.DoesNotExist:
        pass

    # Cas 2 : Order avec compte (flux legacy, rarement utilisé)
    try:
        order = Order.objects.get(uuid=access_token)
        # Order n'a pas de page de confirmation publique par token.
        # On redirige vers la home — le client pourra retrouver ses
        # billets via son espace utilisateur.
        return redirect('home')
    except Order.DoesNotExist:
        from django.http import Http404
        raise Http404("Commande introuvable.")


def guest_confirmation(request, access_token):
    from .models import GuestOrder, GuestTicket

    order = get_object_or_404(GuestOrder, access_token=access_token)
    tickets = GuestTicket.objects.filter(order_item__order=order)

    return render(request, 'tickets/guest_confirmation.html', {
        'order': order,
        'tickets': tickets,
    })


def guest_payment_cancel(request, access_token):
    """
    URL appelée si l'acheteur invité annule le paiement sur PayDunya.
    Marque la commande annulée + le Payment associé CANCELLED.
    """
    from .models import GuestOrder
    from apps.payments.models import Payment

    order = get_object_or_404(GuestOrder, access_token=access_token)

    if order.status == GuestOrder.Status.PENDING:
        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])
        order.mark_payment_cancelled()

        Payment.objects.filter(
            guest_order=order, status=Payment.Status.PENDING,
        ).update(status=Payment.Status.CANCELLED)

        log_action(
            action=AuditLog.Action.PAYMENT_CANCELLED,
            description=(
                f"Paiement annulé par l'acheteur pour la commande invité "
                f"{order.order_number}. Timestamp d'annulation enregistré pour "
                f"sécurité race condition."
            ),
            model_name='Payment', object_id=order.order_number,
            metadata={'cancelled_at': str(order.payment_cancelled_at)},
            ip_address=get_client_ip(request),
        )

    return redirect('tickets:guest_confirmation', access_token=access_token)


@csrf_exempt
@require_POST
def guest_webhook(request):
    from django.http import HttpResponse
    from .models import GuestOrder
    from apps.payments.models import Payment
    from apps.payments.provider import get_payment_service, get_provider_name

    current_provider = get_provider_name()
    logger.warning(
        "WEBHOOK RECU — provider=%s, IP=%s, Body[:200]=%s",
        current_provider,
        request.META.get('REMOTE_ADDR', '?'),
        (request.body or b'')[:200],
    )

    service = get_payment_service()
    if not service.verify_webhook_signature(request):
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description=f"Webhook invité rejeté : signature {current_provider} invalide",
            model_name='Payment', object_id='',
            ip_address=get_client_ip(request),
        )
        return HttpResponse('FORBIDDEN', status=403)

    try:
        parsed = service.parse_webhook(request)
    except Exception as exc:
        logger.exception("Webhook %s parse error: %s", current_provider, exc)
        return HttpResponse('OK', status=200)

    order_number = parsed['order_number']
    reference = parsed['provider_reference']
    status = parsed['status']
    raw = parsed['raw']

    logger.info("Webhook %s — order=%s, ref=%s, status=%s",
                current_provider, order_number, reference, status)

    if status != 'completed' or not order_number:
        return HttpResponse('OK', status=200)

    try:
        order = GuestOrder.objects.get(
            order_number=order_number, status=GuestOrder.Status.PENDING,
        )
    except GuestOrder.DoesNotExist:
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description=f"Webhook {current_provider} : commande {order_number} introuvable/annulée",
            model_name='Payment', object_id=order_number,
            ip_address=get_client_ip(request),
        )
        return HttpResponse('OK', status=200)

    # 🔒 Garde-fou : la Payment doit correspondre au provider actif
    payment = Payment.objects.filter(
        guest_order=order, provider=current_provider,
    ).first()
    if not payment:
        logger.critical(
            "Webhook %s : aucune Payment pour %s (provider mismatch)",
            current_provider, order_number,
        )
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description=f"Webhook {current_provider} : Payment absente pour {order_number}",
            model_name='Payment', object_id=order_number,
            ip_address=get_client_ip(request),
        )
        return HttpResponse('PROVIDER_MISMATCH', status=400)

    # Vérification serveur-à-serveur
    verify_result = service.verify_payment(reference)

    # 🛡️ Fallback : si l'API status ne renvoie pas le montant mais que le
    # webhook le contient, on utilise celui du webhook (comme pour PayDunya).
    if verify_result.get('amount') is None:
        webhook_amount = (raw or {}).get('amount')
        if webhook_amount is not None:
            try:
                verify_result['amount'] = int(webhook_amount)
                logger.info("Fallback montant depuis webhook: %s",
                            verify_result['amount'])
            except (TypeError, ValueError):
                pass

    if not (verify_result.get('success')
            and verify_result.get('status') == 'completed'):
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description=f"Webhook {current_provider} : vérif API échouée pour {order_number}",
            model_name='Payment', object_id=order_number,
            ip_address=get_client_ip(request),
        )
        return HttpResponse('OK', status=200)

    # Vérification montant + binding
    from apps.payments.verification import verify_payment_amount_and_binding
    verif = verify_payment_amount_and_binding(verify_result, order, reference)
    if not verif['ok']:
        logger.critical(
            "Webhook %s rejeté (%s) : %s attendu=%s reçu=%s",
            current_provider, order_number, verif['reason'],
            verif.get('expected'), verif.get('received'),
        )
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description=f"Webhook {current_provider} rejeté {order_number} : {verif['reason']}",
            model_name='Payment', object_id=order_number,
            metadata={'expected': str(verif.get('expected')),
                      'received': str(verif.get('received'))},
            ip_address=get_client_ip(request),
        )
        return HttpResponse('VERIFICATION_FAILED', status=400)

    newly_confirmed = order.mark_as_paid(
        payment_method=current_provider, payment_reference=reference,
    )
    if newly_confirmed:
        Payment.objects.filter(guest_order=order).update(
            status=Payment.Status.COMPLETED,
            completed_at=timezone.now(),
            raw_response=raw,
        )
        log_action(
            action=AuditLog.Action.PAYMENT_SUCCESS,
            description=f"Paiement confirmé ({current_provider}) {order.order_number}",
            model_name='Payment', object_id=order.order_number,
            metadata={'provider': current_provider, 'amount': str(order.total)},
            ip_address=get_client_ip(request),
        )
        from apps.notifications.tasks import send_guest_ticket_email_async
        send_guest_ticket_email_async.delay(str(order.uuid))
    return HttpResponse('OK', status=200)


def download_guest_ticket_pdf(request, access_token):
    """
    Téléchargement PDF du billet invité — sans compte requis.
    Accessible via le lien unique dans l'email de confirmation.
    ✅ Fix IDOR : utilise access_token au lieu de ticket_number.
    """
    from .models import GuestTicket
    from .utils import generate_guest_ticket_pdf

    ticket = get_object_or_404(
        GuestTicket,
        access_token=access_token,
    )

    pdf_bytes = generate_guest_ticket_pdf(ticket)
    response  = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="billet-{ticket.ticket_number}.pdf"'
    )
    return response


def online_access_redirect(request, token):
    """
    Page d'accès à un événement en ligne.
    L'acheteur reçoit dans son email une URL unique
    (/billets/live/<token>/) qui pointe ici.
    """
    from .models import GuestTicket

    ticket = get_object_or_404(GuestTicket, online_access_token=token)
    event = ticket.event

    invalid_reason = None
    if ticket.status == GuestTicket.Status.VOID:
        invalid_reason = "Ce billet a été annulé. Le lien d'accès n'est plus valide."
    elif event.event_type not in ('online', 'hybrid'):
        invalid_reason = "Cet événement n'est pas un événement en ligne."
    elif not event.online_link:
        invalid_reason = (
            "Le lien de connexion n'a pas encore été renseigné par "
            "l'organisateur. Merci de réessayer plus tard."
        )
    elif event.status == Event.Status.CANCELLED:
        invalid_reason = "Cet événement a été annulé."

    log_action(
        action=AuditLog.Action.ONLINE_ACCESS,
        description=(
            f"Accès en ligne pour le billet {ticket.ticket_number} "
            f"(commande {ticket.order_item.order.order_number})"
            + (f" — refusé : {invalid_reason}" if invalid_reason else "")
        ),
        model_name='GuestTicket',
        object_id=str(ticket.pk),
        metadata={
            'ticket_number': ticket.ticket_number,
            'order_number': ticket.order_item.order.order_number,
            'event_slug': event.slug,
            'valid': invalid_reason is None,
        },
        ip_address=get_client_ip(request),
    )

    if invalid_reason:
        return render(request, 'tickets/online_access_invalid.html', {
            'reason': invalid_reason,
            'event': event,
            'ticket': ticket,
        })

    return render(request, 'tickets/online_access.html', {
        'event': event,
        'ticket': ticket,
        'online_link': event.online_link,
    })