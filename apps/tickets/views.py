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
#
# L'achat "avec compte" (panier, checkout, mes billets, téléchargement PDF
# authentifié) a été entièrement remplacé par le tunnel invité ci-dessous
# (GUEST CHECKOUT). Les vues correspondantes contenaient un
# `return redirect('home')` suivi de logique inatteignable — supprimée ici.
#
# Trois routes sont conservées à l'état de simples redirections, car
# apps/payments/views.py (ancien flux de paiement "avec compte") les
# référence encore explicitement (initiate_payment, payment_return,
# payment_cancel) : 'tickets:cart', 'tickets:checkout', 'tickets:confirmation'.
# Les routes sans dépendance externe (panier ajouter/retirer, mes billets,
# détail billet, PDF) ont été supprimées avec leurs templates et leurs URLs.
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
                selected_items.append({'ticket_type': tt, 'quantity': qty, 'unit_price': tt.price, 'subtotal': subtotal})

        errors = []
        if not first_name: errors.append("Le prénom est requis.")
        if not last_name: errors.append("Le nom est requis.")
        if not email: errors.append("L'email est requis.")
        if not selected_items: errors.append("Sélectionnez au moins un billet.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'tickets/guest_checkout.html', {'event': event, 'ticket_types': ticket_types})

        order = GuestOrder.objects.create(
            first_name=first_name, last_name=last_name, email=email, phone=phone,
            subtotal=total, total=total, status=GuestOrder.Status.PENDING,
        )

        # Verrouille chaque type de billet le temps de vérifier ET de
        # décrémenter le stock — empêche la survente si plusieurs acheteurs
        # (avec ou sans compte) valident en même temps.
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
                    return render(request, 'tickets/guest_checkout.html', {'event': event, 'ticket_types': ticket_types})

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
            metadata={'total': str(total), 'is_free': total == 0, 'email': email},
            ip_address=get_client_ip(request),
        )

        if total == 0:
            order.mark_as_paid(payment_method='free', payment_reference=f'FREE-{order.order_number}')
            log_action(
                action=AuditLog.Action.PAYMENT_SUCCESS,
                description=f"Commande invité {order.order_number} confirmée (gratuite)",
                model_name='Payment', object_id=order.order_number,
                metadata={'provider': 'free', 'amount': '0'},
                ip_address=get_client_ip(request),
            )
            # Envoi asynchrone des billets par email (commande gratuite, invité)
            from apps.notifications.tasks import send_guest_ticket_email_async
            send_guest_ticket_email_async.delay(str(order.uuid))
            return redirect('tickets:guest_confirmation', order_number=order.order_number)
        return redirect('tickets:guest_payment', order_number=order.order_number)

    return render(request, 'tickets/guest_checkout.html', {'event': event, 'ticket_types': ticket_types})


def guest_payment_initiate(request, order_number):
    from .models import GuestOrder
    from django.conf import settings
    import requests

    order = get_object_or_404(GuestOrder, order_number=order_number)

    if order.status == GuestOrder.Status.PAID:
        return redirect('tickets:guest_confirmation', order_number=order_number)

    from apps.payments.models import Payment
    payment, _created = Payment.objects.get_or_create(
        guest_order=order,
        defaults={'amount': order.total, 'provider': Payment.Provider.PAYDUNYA},
    )
    if payment.status != Payment.Status.PENDING:
        # Nouvelle tentative après un échec/annulation précédent — on
        # réutilise la même ligne plutôt que d'en créer une nouvelle.
        payment.status = Payment.Status.PENDING
        payment.amount = order.total
        payment.save(update_fields=['status', 'amount'])

    base_url = settings.PAYDUNYA_BASE_URL
    return_url = f"{base_url}/billets/guest/retour/{order.order_number}/"
    cancel_url = f"{base_url}/billets/guest/annulation/{order.order_number}/"
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
        "invoice": {"items": invoice_items, "taxes": {}, "total_amount": str(int(order.total)),
                    "description": f"Billets IvoirPass — {order.order_number}"},
        "actions": {"cancel_url": cancel_url, "return_url": return_url, "callback_url": webhook_url},
        "custom_data": {"guest_order_number": order.order_number, "buyer_email": order.email, "buyer_name": order.buyer_name}
    }

    headers = {
        'Content-Type': 'application/json',
        'PAYDUNYA-MASTER-KEY': settings.PAYDUNYA_MASTER_KEY,
        'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
        'PAYDUNYA-TOKEN': settings.PAYDUNYA_TOKEN,
    }

    try:
        response = requests.post(settings.PAYDUNYA_API_BASE + '/checkout-invoice/create', json=payload, headers=headers, timeout=30)
        data = response.json()
        if data.get('response_code') == '00':
            token = data['token']
            request.session[f'guest_paydunya_token_{order_number}'] = token
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


def guest_payment_return(request, order_number):
    """Retour après paiement PayDunya — commande invité."""
    from .models import GuestOrder
    from apps.payments.paydunya import PayDunyaService

    order = get_object_or_404(GuestOrder, order_number=order_number)

    # Si déjà payé
    if order.status == GuestOrder.Status.PAID:
        messages.success(request, "🎉 Votre paiement a été confirmé !")
        return redirect('tickets:guest_confirmation', order_number=order_number)

    # Récupère le token
    token = request.GET.get('token', '').strip() or order.payment_reference or ''

    if token:
        result = PayDunyaService.verify_payment(token)
        
        if result.get('success') and result.get('status') == 'completed':
            # ✅ CORRECTIF CRITIQUE : mark_as_paid() refuse désormais
            # explicitement si order.is_payment_cancelled() (annulée il y a
            # moins de 2h) — voir apps/tickets/models.py. On distingue ce
            # cas pour afficher un message clair plutôt que de laisser
            # croire que le paiement est "en cours de vérification".
            if order.is_payment_cancelled():
                messages.error(
                    request,
                    "❌ Votre paiement avait été annulé. Il ne peut pas être "
                    "relancé dans les 2 heures. Veuillez contacter le support."
                )
                return redirect('tickets:guest_confirmation', order_number=order_number)

            # mark_as_paid() est verrouillé et idempotent : si le webhook a
            # déjà confirmé la commande entre-temps, il renvoie False et on
            # évite de dupliquer le log d'audit et l'email des billets.
            newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference=token)
            if newly_confirmed:
                from apps.payments.models import Payment
                Payment.objects.filter(guest_order=order).update(
                    status=Payment.Status.COMPLETED,
                    completed_at=timezone.now(),
                    raw_response=result,
                )
                log_action(
                    action=AuditLog.Action.PAYMENT_SUCCESS,
                    description=f"Paiement confirmé (retour) pour la commande invité {order_number}",
                    model_name='Payment', object_id=order_number,
                    metadata={'provider': 'paydunya', 'amount': str(order.total)},
                    ip_address=get_client_ip(request),
                )
                # Envoi asynchrone des billets par email (commande payante, invité)
                from apps.notifications.tasks import send_guest_ticket_email_async
                send_guest_ticket_email_async.delay(str(order.uuid))
            messages.success(request, f"🎉 Paiement confirmé !")
            return redirect('tickets:guest_confirmation', order_number=order_number)

    messages.info(request, "⏳ Vérification du paiement en cours...")
    return redirect('tickets:guest_confirmation', order_number=order_number)


def guest_confirmation(request, order_number):
    from .models import GuestOrder, GuestTicket

    order = get_object_or_404(GuestOrder, order_number=order_number)
    tickets = GuestTicket.objects.filter(order_item__order=order)
    return render(request, 'tickets/guest_confirmation.html', {'order': order, 'tickets': tickets})


def guest_payment_cancel(request, order_number):
    """
    URL appelee si l'acheteur invite annule le paiement sur PayDunya.
    Marque la commande comme annulee (au lieu de rester PENDING
    indefiniment) et affiche un message clair, distinct de l'attente
    de confirmation.

    ✅ CORRECTIF CRITIQUE : avant, cette vue changeait le statut de la
    commande mais ne touchait jamais le Payment associé (resté PENDING)
    ni n'enregistrait de timestamp d'annulation. La tâche de
    réconciliation périodique retombait alors sur ce Payment PENDING,
    revérifiait chez PayDunya, et confirmait la commande malgré son
    annulation — d'où une commande annulée qui « ressuscitait » payée
    quelques minutes plus tard. mark_payment_cancelled() + le passage
    des Payment PENDING à CANCELLED ferment ce trou, avec la même
    fenêtre de sécurité de 2h que le tunnel "avec compte".
    """
    from .models import GuestOrder, GuestTicket
    from apps.payments.models import Payment

    order = get_object_or_404(GuestOrder, order_number=order_number)

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
                f"{order_number}. Timestamp d'annulation enregistré pour "
                f"sécurité race condition."
            ),
            model_name='Payment', object_id=order_number,
            metadata={'cancelled_at': str(order.payment_cancelled_at)},
            ip_address=get_client_ip(request),
        )

    tickets = GuestTicket.objects.filter(order_item__order=order)
    return render(request, 'tickets/guest_confirmation.html', {'order': order, 'tickets': tickets})


from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

@csrf_exempt
@require_POST
def guest_webhook(request):
    import json
    from django.http import HttpResponse
    from .models import GuestOrder
    from apps.payments.paydunya import PayDunyaService

    # 🔒 VÉRIFICATION SIGNATURE PAYDUNYA — sans ce contrôle, n'importe qui
    # pouvait POSTer un faux JSON prétendant qu'une commande invité est
    # payée et obtenir des billets gratuits (faille corrigée ici).
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

        # 🔒 VÉRIFICATION SERVEUR-À-SERVEUR — on ne fait jamais confiance
        # au seul contenu du POST reçu : on redemande le statut réel
        # directement à l'API PayDunya avant de considérer le paiement
        # comme confirmé (même logique que le webhook du flux "compte").
        if status == 'completed' and token:
            verify_result = PayDunyaService.verify_payment(token)
            if not (verify_result.get('success') and verify_result.get('status') == 'completed'):
                log_action(
                    action=AuditLog.Action.PAYMENT_FAILED,
                    description=f"Webhook invité : vérification serveur-à-serveur échouée pour {order_number}",
                    model_name='Payment', object_id=order_number,
                    ip_address=get_client_ip(request),
                )
                return HttpResponse('OK', status=200)

        if status == 'completed' and order_number:
            try:
                order = GuestOrder.objects.get(order_number=order_number, status=GuestOrder.Status.PENDING)
                # mark_as_paid() est verrouillé et idempotent, et refuse
                # désormais aussi toute commande annulée il y a moins de 2h
                # (voir apps/tickets/models.py) : si le retour navigateur a
                # déjà confirmé la commande entre-temps, il renvoie False et
                # on évite de dupliquer log/email.
                newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference=token)
                if newly_confirmed:
                    from apps.payments.models import Payment
                    Payment.objects.filter(guest_order=order).update(
                        status=Payment.Status.COMPLETED,
                        completed_at=timezone.now(),
                        raw_response=data,
                    )
                    log_action(
                        action=AuditLog.Action.PAYMENT_SUCCESS,
                        description=f"Paiement confirmé (webhook) pour la commande invité {order_number}",
                        model_name='Payment', object_id=order_number,
                        metadata={'provider': 'paydunya', 'amount': str(order.total)},
                        ip_address=get_client_ip(request),
                    )
                    # Envoi asynchrone des billets par email (commande payante, invité — via webhook)
                    from apps.notifications.tasks import send_guest_ticket_email_async
                    send_guest_ticket_email_async.delay(str(order.uuid))
            except GuestOrder.DoesNotExist:
                # ✅ Couvre aussi le cas d'une commande CANCELLED : le
                # filtre status=PENDING ci-dessus l'exclut déjà (protection
                # « par accident » avant ce correctif), on le trace
                # explicitement pour ne pas le confondre avec une commande
                # réellement inexistante.
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
    except:
        return HttpResponse('OK', status=200)

def download_guest_ticket_pdf(request, ticket_number):
    """
    Téléchargement PDF du billet invité — sans compte requis.
    Accessible via le lien unique dans l'email de confirmation.
    """
    from .models import GuestTicket
    from .utils import generate_guest_ticket_pdf

    ticket = get_object_or_404(
        GuestTicket,
        ticket_number=ticket_number,
    )

    pdf_bytes = generate_guest_ticket_pdf(ticket)
    response  = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="billet-{ticket.ticket_number}.pdf"'
    )
    return response