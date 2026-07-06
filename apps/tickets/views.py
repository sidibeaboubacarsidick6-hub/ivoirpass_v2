"""
IvoirPass V2 — Vues billetterie
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone

from apps.events.models import Event, TicketType
from .models import Order, OrderItem, Ticket
from .utils import generate_ticket_pdf


# ============================================
# PANIER
# ============================================

def get_cart(request):
    return request.session.get('cart', {})

def save_cart(request, cart):
    request.session['cart'] = cart
    request.session.modified = True


def add_to_cart(request, ticket_type_id):
    ticket_type = get_object_or_404(TicketType, pk=ticket_type_id)
    event = ticket_type.event

    if not event.is_on_sale:
        messages.error(request, "Cet événement n'est pas en vente.")
        return redirect('events:detail', slug=event.slug)

    if ticket_type.is_sold_out:
        messages.error(request, "Ce type de ticket est épuisé.")
        return redirect('events:detail', slug=event.slug)

    cart = get_cart(request)
    key = str(ticket_type_id)
    quantity = int(request.POST.get('quantity', 1))
    quantity = max(1, min(quantity, ticket_type.max_per_order))

    if key in cart:
        new_qty = cart[key]['quantity'] + quantity
        new_qty = min(new_qty, ticket_type.max_per_order)
        cart[key]['quantity'] = new_qty
    else:
        cart[key] = {
            'ticket_type_id': ticket_type_id,
            'event_id': event.id,
            'event_title': event.title,
            'event_slug': event.slug,
            'ticket_name': ticket_type.name,
            'price': str(ticket_type.price),
            'quantity': quantity,
        }

    save_cart(request, cart)
    messages.success(request, f"{quantity} billet(s) « {ticket_type.name} » ajouté(s).")
    return redirect('tickets:cart')


def remove_from_cart(request, ticket_type_id):
    cart = get_cart(request)
    key = str(ticket_type_id)
    if key in cart:
        del cart[key]
        save_cart(request, cart)
        messages.success(request, "Article retiré du panier.")
    return redirect('tickets:cart')


def cart_view(request):
    cart = get_cart(request)
    items = []
    total = 0

    for key, item in cart.items():
        subtotal = int(float(item['price'])) * item['quantity']
        total += subtotal
        items.append({**item, 'subtotal': subtotal, 'key': key})

    return render(request, 'tickets/cart.html', {
        'items': items,
        'total': total,
    })


# ============================================
# CHECKOUT
# ============================================

@login_required
def checkout(request):
    cart = get_cart(request)

    if not cart:
        messages.warning(request, "Votre panier est vide.")
        return redirect('tickets:cart')

    items = []
    total = 0
    all_free = True

    for key, item in cart.items():
        try:
            tt = TicketType.objects.select_related('event').get(pk=item['ticket_type_id'])
        except TicketType.DoesNotExist:
            continue
        subtotal = int(float(item['price'])) * item['quantity']
        total += subtotal
        if subtotal > 0:
            all_free = False
        items.append({**item, 'subtotal': subtotal, 'ticket_type_obj': tt})

    if request.method == 'POST':
        order = Order.objects.create(
            buyer=request.user,
            subtotal=total,
            commission=0,
            total=total,
            status=Order.Status.PENDING,
        )

        for item_data in items:
            tt = item_data['ticket_type_obj']
            OrderItem.objects.create(
                order=order,
                ticket_type=tt,
                quantity=item_data['quantity'],
                unit_price=tt.price,
            )
            tt.quantity_sold += item_data['quantity']
            tt.save(update_fields=['quantity_sold'])
            tt.event.tickets_sold += item_data['quantity']
            tt.event.save(update_fields=['tickets_sold'])

            if tt.quantity > 0 and tt.quantity_sold >= tt.quantity:
                tt.event.status = 'completed'
                tt.event.save(update_fields=['status'])

        save_cart(request, {})

        if all_free:
            order.mark_as_paid(payment_method='free', payment_reference=f"FREE-{order.order_number}")
            messages.success(request, "🎉 Inscription confirmée !")
            return redirect('tickets:confirmation', order_number=order.order_number)
        else:
            return redirect('payments:initiate', order_number=order.order_number)

    return render(request, 'tickets/checkout.html', {
        'items': items,
        'total': total,
        'all_free': all_free,
    })


# ============================================
# CONFIRMATION
# ============================================


def order_confirmation(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, buyer=request.user, status=Order.Status.PAID)
    tickets = Ticket.objects.filter(order_item__order=order)
    return render(request, 'tickets/confirmation.html', {'order': order, 'tickets': tickets})


@login_required
def my_tickets(request):
    tickets = Ticket.objects.filter(order_item__order__buyer=request.user, order_item__order__status=Order.Status.PAID)
    now = timezone.now()
    upcoming = [t for t in tickets if t.event.start_date >= now]
    past = [t for t in tickets if t.event.start_date < now]
    return render(request, 'tickets/my_tickets.html', {'upcoming': upcoming, 'past': past})


@login_required
def ticket_detail(request, ticket_number):
    ticket = get_object_or_404(Ticket, ticket_number=ticket_number, order_item__order__buyer=request.user)
    return render(request, 'tickets/ticket_detail.html', {'ticket': ticket})


@login_required
def download_ticket_pdf(request, ticket_number):
    ticket = get_object_or_404(Ticket, ticket_number=ticket_number, order_item__order__buyer=request.user)
    pdf_bytes = generate_ticket_pdf(ticket)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="billet-{ticket.ticket_number}.pdf"'
    return response


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

        for item in selected_items:
            GuestOrderItem.objects.create(
                order=order, ticket_type=item['ticket_type'],
                quantity=item['quantity'], unit_price=item['unit_price'],
            )
            tt = item['ticket_type']
            tt.quantity_sold += item['quantity']
            tt.event.tickets_sold += item['quantity']
            tt.save(update_fields=['quantity_sold'])
            tt.event.save(update_fields=['tickets_sold'])

        return redirect('tickets:guest_payment', order_number=order.order_number)

    return render(request, 'tickets/guest_checkout.html', {'event': event, 'ticket_types': ticket_types})


def guest_payment_initiate(request, order_number):
    from .models import GuestOrder
    from django.conf import settings
    import requests

    order = get_object_or_404(GuestOrder, order_number=order_number)

    if order.status == GuestOrder.Status.PAID:
        return redirect('tickets:guest_confirmation', order_number=order_number)

    base_url = settings.PAYDUNYA_BASE_URL
    return_url = f"{base_url}/billets/guest/retour/{order.order_number}/"
    cancel_url = f"{base_url}/billets/guest/annulation/{order.order_number}/"
    webhook_url = f"{base_url}/billets/guest/webhook/"

    invoice_items = {}
    for i, item in enumerate(order.guest_items.all(), 1):
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
            return redirect(data['response_text'])
        else:
            messages.error(request, f"Erreur PayDunya : {data.get('response_text')}")
    except Exception as e:
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
            order.mark_as_paid(payment_method='paydunya', payment_reference=token)
            messages.success(request, f"🎉 Paiement confirmé !")
            return redirect('tickets:guest_confirmation', order_number=order_number)

    messages.info(request, "⏳ Vérification du paiement en cours...")
    return redirect('tickets:guest_confirmation', order_number=order_number)


def guest_confirmation(request, order_number):
    from .models import GuestOrder, GuestTicket

    order = get_object_or_404(GuestOrder, order_number=order_number)
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

    try:
        data = json.loads(request.body)
        invoice_data = data.get('data', {})
        custom_data = invoice_data.get('custom_data', {})
        status = invoice_data.get('invoice', {}).get('status', '')
        token = invoice_data.get('invoiceToken', '')
        order_number = custom_data.get('guest_order_number', '')

        if status == 'completed' and order_number:
            try:
                order = GuestOrder.objects.get(order_number=order_number, status=GuestOrder.Status.PENDING)
                order.mark_as_paid(payment_method='paydunya', payment_reference=token)
            except GuestOrder.DoesNotExist:
                pass
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
