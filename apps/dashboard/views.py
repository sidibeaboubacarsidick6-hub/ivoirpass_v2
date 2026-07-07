"""
IvoirPass V2 — Vues du Dashboard Organisateur
"""
from django.shortcuts import render, redirect, get_object_or_404  # ✅ Correction : enlever la virgule finale
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import (
    Sum, Count, F, Q,
    ExpressionWrapper, DecimalField, IntegerField
)
from django.utils import timezone
from datetime import timedelta

from apps.events.models import Event
from apps.tickets.models import Order, OrderItem, Ticket
from .models import OrganizerWallet, WalletTransaction, WithdrawalRequest, ReversalOTP



def organizer_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_organizer or request.user.is_platform_admin):
            messages.error(request, "Section réservée aux organisateurs.")
            return redirect('accounts:profile')
        return view_func(request, *args, **kwargs)
    return wrapper


@organizer_required
def dashboard_index(request):
    user   = request.user
    events = Event.objects.filter(organizer=user)
    now    = timezone.now()
    thirty_days_ago = now - timedelta(days=30)

    total_events     = events.count()
    published_events = events.filter(status='published').count()
    total_tickets    = events.aggregate(t=Sum('tickets_sold'))['t'] or 0

    wallet, _ = OrganizerWallet.objects.get_or_create(organizer=user)

    # Revenus billetterie — brut et net
    ticket_items = OrderItem.objects.filter(
        ticket_type__event__organizer=user,
        order__status=Order.Status.PAID,
    )
    tickets_gross = ticket_items.aggregate(t=Sum('subtotal'))['t'] or 0

    tickets_net = 0
    for item in ticket_items.select_related('ticket_type__event'):
        rate = float(item.ticket_type.event.commission_rate) / 100
        tickets_net += float(item.subtotal) * (1 - rate)

    # Revenus boutique — brut et net
    from apps.store.models import ProductOrder
    store_orders = ProductOrder.objects.filter(
        product__seller=user,
        status='paid',
    )
    store_gross = store_orders.aggregate(t=Sum('subtotal'))['t'] or 0

    store_net = 0
    for order in store_orders.select_related('product'):
        rate = float(order.product.commission_rate) / 100
        store_net += float(order.subtotal) * (1 - rate)

    total_gross = float(tickets_gross) + float(store_gross)
    total_net   = tickets_net + store_net
    total_commission = total_gross - total_net

    recent_items = ticket_items.filter(order__paid_at__gte=thirty_days_ago)
    revenue_30d  = recent_items.aggregate(t=Sum('subtotal'))['t'] or 0
    tickets_30d  = recent_items.aggregate(t=Sum('quantity'))['t'] or 0

    sales_by_day = []
    for i in range(29, -1, -1):
        day = now - timedelta(days=i)
        day_sales = ticket_items.filter(
            order__paid_at__date=day.date()
        ).aggregate(t=Sum('subtotal'))['t'] or 0
        sales_by_day.append({
            'date':   day.strftime('%d/%m'),
            'amount': int(day_sales),
        })

    fill_rates = [e.occupancy_rate for e in events.filter(total_capacity__gt=0)]
    avg_fill_rate = round(sum(fill_rates) / len(fill_rates), 1) if fill_rates else 0

    next_event = events.filter(
        status='published', start_date__gte=now
    ).order_by('start_date').first()

    recent_events = events.order_by('-created_at')[:5]

    return render(request, 'dashboard/index.html', {
        'wallet':            wallet,
        'total_events':      total_events,
        'published_events':  published_events,
        'total_tickets':     total_tickets,
        'revenue_30d':       revenue_30d,
        'tickets_30d':       tickets_30d,
        'avg_fill_rate':     avg_fill_rate,
        'next_event':        next_event,
        'recent_events':     recent_events,
        'sales_by_day':      sales_by_day,
        # Détail brut/net consolidé
        'tickets_gross':     tickets_gross,
        'tickets_net':       round(tickets_net),
        'store_gross':       store_gross,
        'store_net':         round(store_net),
        'total_gross':       round(total_gross),
        'total_net':         round(total_net),
        'total_commission':  round(total_commission),
    })


@organizer_required
def event_stats(request, slug):
    """Statistiques détaillées d'un événement."""
    from decimal import Decimal

    event = get_object_or_404(Event, slug=slug, organizer=request.user)

    # Stats par type de ticket
    ticket_stats = []
    gross_revenue = Decimal('0')

    for tt in event.ticket_types.all():
        revenue = Decimal(str(tt.quantity_sold)) * tt.price
        gross_revenue += revenue
        fill = round(
            (tt.quantity_sold / tt.quantity * 100), 1
        ) if tt.quantity > 0 else 0
        ticket_stats.append({
            'ticket_type': tt,
            'sold':        tt.quantity_sold,
            'remaining':   tt.remaining,
            'revenue':     revenue,
            'fill_rate':   fill,
        })

    # Commission dynamique — tout en Decimal
    commission_rate = event.commission_rate / Decimal('100')
    commission      = gross_revenue * commission_rate
    net_revenue     = gross_revenue - commission

    # Commandes récentes
    recent_orders = Order.objects.filter(
        items__ticket_type__event=event,
        status=Order.Status.PAID
    ).distinct().select_related('buyer').order_by('-paid_at')[:20]

    # Timeline des ventes
    sales_timeline = []
    if event.published_at:
        start = event.published_at.date()
        end   = min(timezone.now().date(), event.start_date.date())
        delta = (end - start).days + 1
        for i in range(min(delta, 30)):
            day     = start + timedelta(days=i)
            day_qty = OrderItem.objects.filter(
                ticket_type__event=event,
                order__status=Order.Status.PAID,
                order__paid_at__date=day
            ).aggregate(t=Sum('quantity'))['t'] or 0
            sales_timeline.append({
                'date': day.strftime('%d/%m'),
                'qty':  day_qty,
            })

    # Stats participants
    total_participants = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
    ).count()

    scanned_count = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
        status='used'
    ).count()

    return render(request, 'dashboard/event_stats.html', {
        'event':              event,
        'ticket_stats':       ticket_stats,
        'recent_orders':      recent_orders,
        'gross_revenue':      gross_revenue,
        'net_revenue':        net_revenue,
        'commission':         commission,
        'commission_rate':    event.commission_rate,
        'sales_timeline':     sales_timeline,
        'total_participants': total_participants,
        'scanned_count':      scanned_count,
        'tickets_remaining':  event.tickets_remaining,
    })


@organizer_required
def participants(request, slug):
    event = get_object_or_404(Event, slug=slug, organizer=request.user)

    tickets = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
    ).select_related(
        'order_item__ticket_type',
        'order_item__order__buyer',
    ).order_by('-created_at')

    status_filter = request.GET.get('status', '')
    if status_filter:
        tickets = tickets.filter(status=status_filter)

    search = request.GET.get('q', '')
    if search:
        tickets = tickets.filter(
            Q(order_item__order__buyer__email__icontains=search) |
            Q(order_item__order__buyer__first_name__icontains=search) |
            Q(ticket_number__icontains=search)
        )

    stats = {
        'total': tickets.count(),
        'valid': tickets.filter(status='valid').count(),
        'used':  tickets.filter(status='used').count(),
    }

    return render(request, 'dashboard/participants.html', {
        'event':         event,
        'tickets':       tickets,
        'stats':         stats,
        'search':        search,
        'status_filter': status_filter,
    })


@organizer_required
def wallet_view(request):
    wallet, _ = OrganizerWallet.objects.get_or_create(organizer=request.user)
    transactions = wallet.transactions.order_by('-created_at')[:50]
    withdrawals  = wallet.withdrawal_requests.order_by('-created_at')[:10]

    return render(request, 'dashboard/wallet.html', {
        'wallet':       wallet,
        'transactions': transactions,
        'withdrawals':  withdrawals,
    })


@organizer_required
def withdraw_request(request):
    wallet, _ = OrganizerWallet.objects.get_or_create(organizer=request.user)
    MIN_AMOUNT = 5000

    if request.method == 'POST':
        amount = int(request.POST.get('amount', 0))
        method = request.POST.get('payout_method', '')
        phone  = request.POST.get('payout_phone', '').strip()
        name   = request.POST.get('payout_name',  '').strip()

        errors = []
        if amount < MIN_AMOUNT:
            errors.append(f"Montant minimum : {MIN_AMOUNT:,} FCFA.")
        if amount > wallet.balance_available:
            errors.append(
                f"Solde insuffisant. Disponible : "
                f"{wallet.balance_available:,} FCFA."
            )
        if not phone:
            errors.append("Numéro Mobile Money requis.")
        if not name:
            errors.append("Nom du bénéficiaire requis.")
        if not method:
            errors.append("Méthode de paiement requise.")

        pending = wallet.withdrawal_requests.filter(
            status__in=[
                WithdrawalRequest.Status.PENDING,
                WithdrawalRequest.Status.APPROVED,
            ]
        ).exists()
        if pending:
            errors.append("Une demande est déjà en cours.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            wr = WithdrawalRequest.objects.create(
                wallet        = wallet,
                amount        = amount,
                payout_method = method,
                payout_phone  = phone,
                payout_name   = name,
            )
            # Générer l'OTP
            otp = ReversalOTP.generate(wr)

            # Envoyer OTP par email
            from django.core.mail import send_mail
            send_mail(
                subject='[IvoirPass] Code de validation — Reversement',
                message=f'Votre code de validation : {otp.code}\nValable 10 minutes.',
                from_email=None,
                recipient_list=[request.user.email],
                fail_silently=True,
            )

            # Envoyer OTP par SMS (si activé)
            from django.conf import settings
            if settings.SMS_ENABLED and request.user.phone_number:
                try:
                    from apps.notifications.sms import send_sms
                    send_sms(
                        to=request.user.phone_number,
                        message=f'IvoirPass - Code reversement : {otp.code}'
                    )
                except Exception:
                    pass

            # Rediriger vers la page de validation OTP
            return redirect('dashboard:verify_otp', reference=wr.reference)

    return render(request, 'dashboard/withdraw.html', {
        'wallet':     wallet,
        'min_amount': MIN_AMOUNT,
        'methods': [
            ('wave',         'Wave CI'),
            ('orange_money', 'Orange Money CI'),
            ('mtn_momo',     'MTN MoMo CI'),
            ('moov',         'Moov Money'),
        ],
    })


import csv
from django.http import HttpResponse

@organizer_required
def export_participants_csv(request, slug):
    """Exporte la liste des participants en CSV."""
    event = get_object_or_404(Event, slug=slug, organizer=request.user)

    tickets = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
    ).select_related(
        'order_item__ticket_type',
        'order_item__order__buyer',
    ).order_by('-created_at')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="participants_{event.slug}.csv"'
    )
    response.write('\ufeff')  # BOM pour Excel UTF-8

    writer = csv.writer(response)
    writer.writerow([
        'Nom complet', 'Email', 'Téléphone', 'Type de billet',
        'Numéro ticket', 'Statut', 'Date achat'
    ])

    for ticket in tickets:
        buyer = ticket.order_item.order.buyer
        writer.writerow([
            buyer.get_full_name(),
            buyer.email,
            buyer.phone_number or '',
            ticket.order_item.ticket_type.name,
            ticket.ticket_number,
            ticket.get_status_display(),
            ticket.created_at.strftime('%d/%m/%Y %H:%M'),
        ])

    return response


# ============================================
# VUES DES COMMANDES PHYSIQUES
# ============================================

@organizer_required
def physical_orders(request):
    """
    Liste des commandes physiques (avec et sans compte) à traiter/livrer.
    """
    from apps.store.models import ProductOrder, GuestProductOrder

    # Commandes avec compte
    orders_with_account = ProductOrder.objects.filter(
        product__seller=request.user,
        product__product_type__in=['physical', 'bundle'],
        status='paid',
    ).select_related('product', 'buyer').order_by('-paid_at')

    # Commandes sans compte
    guest_orders = GuestProductOrder.objects.filter(
        product__seller=request.user,
        product__product_type__in=['physical', 'bundle'],
        status='paid',
    ).select_related('product').order_by('-paid_at')

    # Fusionne et trie par date
    all_orders = []
    for o in orders_with_account:
        all_orders.append({
            'type': 'account', 
            'order': o,
            'buyer_name': o.buyer.get_full_name(),
            'buyer_phone': o.buyer.phone_number,
            'paid_at': o.paid_at,
        })
    for o in guest_orders:
        all_orders.append({
            'type': 'guest', 
            'order': o,
            'buyer_name': o.buyer_name,
            'buyer_phone': o.phone,
            'paid_at': o.paid_at,
        })

    all_orders.sort(key=lambda x: x['paid_at'] or timezone.now(), reverse=True)

    stats = {
        'pending':   len([o for o in all_orders if o['order'].status == 'paid']),
        'shipped':   len([o for o in all_orders if o['order'].status == 'shipped']),
        'delivered': len([o for o in all_orders if o['order'].status == 'delivered']),
    }

    return render(request, 'dashboard/physical_orders.html', {
        'all_orders': all_orders,
        'stats': stats,
    })


@organizer_required
def mark_order_shipped(request, order_type, order_id):
    """Marque une commande physique comme expédiée avec numéro de suivi."""
    from apps.store.models import ProductOrder, GuestProductOrder

    if order_type == 'account':
        order = get_object_or_404(ProductOrder, pk=order_id, product__seller=request.user)
    else:
        order = get_object_or_404(GuestProductOrder, pk=order_id, product__seller=request.user)

    if request.method == 'POST':
        tracking = request.POST.get('tracking_number', '').strip()
        order.tracking_number = tracking
        order.status = 'shipped'
        order.shipped_at = timezone.now()
        order.save()
        messages.success(request, f"Commande {order.order_number} marquée comme expédiée.")

    return redirect('dashboard:physical_orders')

@organizer_required
def verify_otp(request, reference):
    """Page de validation du code OTP pour reversement."""
    withdrawal = get_object_or_404(
        WithdrawalRequest,
        reference=reference,
        wallet__organizer=request.user,
        status=WithdrawalRequest.Status.PENDING
    )

    try:
        otp = withdrawal.otp
    except ReversalOTP.DoesNotExist:
        messages.error(request, "Aucun code OTP trouvé. Refaites votre demande.")
        return redirect('dashboard:wallet')

    if request.method == 'POST':
        code = request.POST.get('otp_code', '').strip()

        if not otp.is_valid:
            messages.error(request, "Code expiré. Refaites votre demande.")
            return redirect('dashboard:wallet')

        if code == otp.code:
            otp.is_used = True
            otp.save()
            messages.success(
                request,
                f"✅ Demande {withdrawal.reference} validée ! Traitement sous 24-48h."
            )
            return redirect('dashboard:wallet')
        else:
            messages.error(request, "Code incorrect. Veuillez réessayer.")

    return render(request, 'dashboard/verify_otp.html', {
        'withdrawal': withdrawal,
        'expires_at': otp.expires_at,
    })