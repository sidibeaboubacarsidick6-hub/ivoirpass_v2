"""
IvoirPass V2 — Vues billetterie
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction

from apps.events.models import Event, TicketType
from apps.dashboard.models import AuditLog
from apps.dashboard.services import log_action, get_client_ip


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
    from .models import GuestOrder
    from django.conf import settings
    import requests

    order = get_object_or_404(GuestOrder, access_token=access_token)

    if order.status == GuestOrder.Status.PAID:
        return redirect('tickets:guest_confirmation', access_token=access_token)

    from apps.payments.models import Payment
    payment, _created = Payment.objects.get_or_create(
        guest_order=order,
        defaults={'amount': order.total, 'provider': Payment.Provider.PAYDUNYA},
    )
    if payment.status != Payment.Status.PENDING:
        payment.status = Payment.Status.PENDING
        payment.amount = order.total
        payment.save(update_fields=['status', 'amount'])

    base_url = settings.PAYDUNYA_BASE_URL
    return_url  = f"{base_url}/billets/guest/retour/{order.access_token}/"
    cancel_url  = f"{base_url}/billets/guest/annulation/{order.access_token}/"
    webhook_url = f"{base_url}/billets/guest/webhook/"

    invoice_items = {}
    for i, item in enumerate(order.guest_items.select_related('ticket_type__event'), 1):
        invoice_items[f"item_{i}"] = {
            "name": item.ticket_type.name,
            "quantity": item.quantity,
            "unit_price": str(item.unit_price),
            "total_price": str(item.subtotal),
            "description": f"Billet {item.ticket_type.event.title}",
        }

    payload = {
        "store": {"name": "IvoirPass", "tagline": "Votre billetterie ivoirienne", "website_url": base_url},
        "invoice": {
            "items": invoice_items, "taxes": {},
            "total_amount": str(int(order.total)),
            "description": f"Billets IvoirPass — {order.order_number}",
        },
        "actions": {"cancel_url": cancel_url, "return_url": return_url, "callback_url": webhook_url},
        "custom_data": {
            "guest_order_number": order.order_number,
            "buyer_email": order.email,
            "buyer_name": order.buyer_name,
        },
    }

    headers = {
        'Content-Type': 'application/json',
        'PAYDUNYA-MASTER-KEY': settings.PAYDUNYA_MASTER_KEY,
        'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
        'PAYDUNYA-TOKEN': settings.PAYDUNYA_TOKEN,
    }

    try:
        response = requests.post(
            settings.PAYDUNYA_API_BASE + '/checkout-invoice/create',
            json=payload, headers=headers, timeout=30,
        )
        data = response.json()
        if data.get('response_code') == '00':
            token = data['token']
            request.session[f'guest_token_{order.order_number}'] = token
            order.payment_reference = token
            order.save(update_fields=['payment_reference'])
            payment.paydunya_token = token
            payment.raw_response = data
            payment.save(update_fields=['paydunya_token', 'raw_response'])
            return redirect(data['response_text'])
        else:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=['status'])
            messages.error(request, f"Erreur PayDunya : {data.get('response_text')}")
    except Exception as e:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])
        messages.error(request, f"Erreur connexion : {e}")

    return redirect('events:detail', slug=order.guest_items.first().ticket_type.event.slug)


def guest_payment_return(request, access_token):
    """Retour après paiement PayDunya — commande invité."""
    from .models import GuestOrder
    from apps.payments.paydunya import PayDunyaService

    order = get_object_or_404(GuestOrder, access_token=access_token)

    if order.status == GuestOrder.Status.PAID:
        messages.success(request, "🎉 Votre paiement a été confirmé !")
        return redirect('tickets:guest_confirmation', access_token=access_token)

    token = request.GET.get('token', '').strip() or order.payment_reference or ''

    if token:
        result = PayDunyaService.verify_payment(token)

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


from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
def guest_webhook(request):
    import json
    from django.http import HttpResponse
    from .models import GuestOrder
    from apps.payments.paydunya import PayDunyaService

    # 🔒 VÉRIFICATION SIGNATURE PAYDUNYA
    if not PayDunyaService.verify_webhook_signature(request):
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description="Webhook invité rejeté : signature PayDunya invalide",
            model_name='Payment', object_id='',
            ip_address=get_client_ip(request),
        )
        return HttpResponse('FORBIDDEN', status=403)

    try:
        data = json.loads(request.body)
        invoice_data = data.get('data', {})
        custom_data = invoice_data.get('custom_data', {})
        status = invoice_data.get('invoice', {}).get('status', '')
        token = invoice_data.get('invoiceToken', '')
        order_number = custom_data.get('guest_order_number', '')

        # 🔒 VÉRIFICATION SERVEUR-À-SERVEUR
        if status == 'completed' and token:
            verify_result = PayDunyaService.verify_payment(token)
            if not (verify_result.get('success') and verify_result.get('status') == 'completed'):
                log_action(
                    action=AuditLog.Action.PAYMENT_FAILED,
                    # ✅ Fix : order_number (pas order.order_number, order n'existe pas encore)
                    description=f"Webhook invité : vérification serveur-à-serveur échouée pour {order_number}",
                    model_name='Payment', object_id=order_number,
                    ip_address=get_client_ip(request),
                )
                return HttpResponse('OK', status=200)

        if status == 'completed' and order_number:
            try:
                order = GuestOrder.objects.get(
                    order_number=order_number, status=GuestOrder.Status.PENDING,
                )
                newly_confirmed = order.mark_as_paid(
                    payment_method='paydunya', payment_reference=token,
                )
                if newly_confirmed:
                    from apps.payments.models import Payment
                    Payment.objects.filter(guest_order=order).update(
                        status=Payment.Status.COMPLETED,
                        completed_at=timezone.now(),
                        raw_response=data,
                    )
                    log_action(
                        action=AuditLog.Action.PAYMENT_SUCCESS,
                        description=f"Paiement confirmé (webhook) pour la commande invité {order.order_number}",
                        model_name='Payment', object_id=order.order_number,
                        metadata={'provider': 'paydunya', 'amount': str(order.total)},
                        ip_address=get_client_ip(request),
                    )
                    from apps.notifications.tasks import send_guest_ticket_email_async
                    send_guest_ticket_email_async.delay(str(order.uuid))
            except GuestOrder.DoesNotExist:
                # ✅ Fix : order_number (pas order.order_number)
                cancelled = GuestOrder.objects.filter(
                    order_number=order_number, status=GuestOrder.Status.CANCELLED,
                ).exists()
                log_action(
                    action=AuditLog.Action.PAYMENT_FAILED,
                    description=(
                        f"Webhook invité : commande {order_number} annulée, paiement non relancé"
                        if cancelled else
                        f"Webhook invité : commande {order_number} introuvable ou déjà traitée"
                    ),
                    model_name='Payment', object_id=order_number,
                    ip_address=get_client_ip(request),
                )
        return HttpResponse('OK', status=200)
    except Exception:
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