"""
IvoirPass V2 — Vues du Dashboard Organisateur
"""
import csv
import openpyxl
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.views import decorators  # ✅ Correction : enlever la virgule finale
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import (
    Sum, Count, F, Q,
    ExpressionWrapper, DecimalField, IntegerField
)
from django.utils import timezone
from datetime import timedelta

from apps.events.models import Event
from apps.tickets.models import Order, OrderItem, Ticket, GuestTicket, GuestOrder
from .models import OrganizerWallet, WalletTransaction, WithdrawalRequest, ReversalOTP, AuditLog, Dispute



def organizer_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_organizer or request.user.is_platform_admin):
            messages.error(request, "Section réservée aux organisateurs.")
            return redirect('accounts:profile')
        return view_func(request, *args, **kwargs)
    return wrapper


def platform_admin_required(view_func):
    """Réservé aux comptes avec le rôle ADMIN (super-admins IvoirPass) —
    distinct de `organizer_required`, qui laisse aussi passer les
    organisateurs pour leurs propres pages.

    À utiliser pour toute vue qui AGIT sur les données de la plateforme
    (validation, modification, remboursement...). Pour une vue qui ne fait
    que consulter/exporter, voir `platform_staff_required` ci-dessous, qui
    inclut aussi Finance/Support/Auditeur."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_platform_admin:
            messages.error(request, "Section réservée aux administrateurs IvoirPass.")
            return redirect('accounts:profile')
        return view_func(request, *args, **kwargs)
    return wrapper


def platform_staff_required(view_func):
    """
    Accès en LECTURE au back-office plateforme : Admin, Finance, Support,
    Auditeur (voir CustomUser.is_platform_staff). N'accorde aucun droit de
    modification — les vues qui agissent sur les données (remboursement,
    changement de statut...) doivent rester derrière `platform_admin_required`.
    """
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_platform_staff:
            messages.error(request, "Section réservée au personnel IvoirPass.")
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

    # Revenus billetterie - brut et net (comptes connectes + invites)
    from apps.tickets.models import GuestOrder, GuestOrderItem
    ticket_items = OrderItem.objects.filter(
        ticket_type__event__organizer=user,
        order__status=Order.Status.PAID,
    )
    guest_ticket_items = GuestOrderItem.objects.filter(
        ticket_type__event__organizer=user,
        order__status=GuestOrder.Status.PAID,
    )
    tickets_gross = (ticket_items.aggregate(t=Sum('subtotal'))['t'] or 0) + (guest_ticket_items.aggregate(t=Sum('subtotal'))['t'] or 0)
    tickets_net = 0
    for item in ticket_items.select_related('ticket_type__event'):
        rate = float(item.ticket_type.event.commission_rate) / 100
        tickets_net += float(item.subtotal) * (1 - rate)
    for item in guest_ticket_items.select_related('ticket_type__event'):
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
        day_sales = (ticket_items.filter(
            order__paid_at__date=day.date()
        ).aggregate(t=Sum('subtotal'))['t'] or 0) + (guest_ticket_items.filter(
            order__paid_at__date=day.date()
        ).aggregate(t=Sum('subtotal'))['t'] or 0)
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
            from apps.tickets.models import GuestOrderItem, GuestOrder
            day_qty = (OrderItem.objects.filter(
                ticket_type__event=event,
                order__status=Order.Status.PAID,
                order__paid_at__date=day
            ).aggregate(t=Sum('quantity'))['t'] or 0) + (GuestOrderItem.objects.filter(
                ticket_type__event=event,
                order__status=GuestOrder.Status.PAID,
                order__paid_at__date=day
            ).aggregate(t=Sum('quantity'))['t'] or 0)
            sales_timeline.append({
                'date': day.strftime('%d/%m'),
                'qty':  day_qty,
            })

    # Stats participants
    from apps.tickets.models import GuestTicket, GuestOrder

    total_participants = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
    ).count() + GuestTicket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=GuestOrder.Status.PAID,
    ).count()

    scanned_count = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
        status='used'
    ).count() + GuestTicket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=GuestOrder.Status.PAID,
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

    # Billets issus des commandes avec compte
    tickets = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
    ).select_related(
        'order_item__ticket_type',
        'order_item__order__buyer',
    )

    # Billets issus des commandes invitées
    guest_tickets = GuestTicket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=GuestOrder.Status.PAID,
    ).select_related(
        'order_item__ticket_type',
        'order_item__order',
    )

    status_filter = request.GET.get('status', '')
    search = request.GET.get('q', '').strip()

    participants_list = []

    for ticket in tickets:
        buyer = ticket.order_item.order.buyer
        participants_list.append({
            'ticket': ticket,
            'buyer_name': buyer.get_full_name(),
            'buyer_email': buyer.email,
            'buyer_phone': buyer.phone_number or '',
            'ticket_type': ticket.order_item.ticket_type.name,
            'ticket_number': ticket.ticket_number,
            'status': ticket.status,
            'status_display': ticket.get_status_display(),
            'scanned_at': ticket.scanned_at,
            'created_at': ticket.created_at,
        })

    for ticket in guest_tickets:
        order = ticket.order_item.order
        participants_list.append({
            'ticket': ticket,
            'buyer_name': order.buyer_name,
            'buyer_email': order.email,
            'buyer_phone': order.phone or '',
            'ticket_type': ticket.order_item.ticket_type.name,
            'ticket_number': ticket.ticket_number,
            'status': ticket.status,
            'status_display': ticket.get_status_display(),
            'scanned_at': ticket.scanned_at,
            'created_at': ticket.created_at,
        })

    if status_filter:
        participants_list = [
            p for p in participants_list
            if p['status'] == status_filter
        ]

    if search:
        search_lower = search.lower()
        participants_list = [
            p for p in participants_list
            if search_lower in p['buyer_name'].lower()
            or search_lower in p['buyer_email'].lower()
            or search_lower in p['ticket_number'].lower()
            or search_lower in p['buyer_phone'].lower()
        ]

    participants_list.sort(
        key=lambda p: p['created_at'],
        reverse=True
    )

    stats = {
        'total': len(participants_list),
        'valid': sum(1 for p in participants_list if p['status'] == 'valid'),
        'used': sum(1 for p in participants_list if p['status'] == 'used'),
    }

    return render(request, 'dashboard/participants.html', {
        'event': event,
        'tickets': participants_list,
        'stats': stats,
        'search': search,
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
            status__in=[WithdrawalRequest.Status.PENDING, WithdrawalRequest.Status.PROCESSING]
        ).exists()
        if pending:
            errors.append("Une demande est déjà en cours.")

        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            with transaction.atomic():
                wallet = OrganizerWallet.objects.select_for_update().get(pk=wallet.pk)
                if amount > wallet.balance_available:
                    messages.error(request, f"Solde insuffisant. Disponible : {wallet.balance_available:,} FCFA.")
                    return redirect('dashboard:withdraw')
                if wallet.withdrawal_requests.filter(status__in=[WithdrawalRequest.Status.PENDING, WithdrawalRequest.Status.PROCESSING]).exists():
                    messages.error(request, "Une demande est déjà en cours.")
                    return redirect('dashboard:wallet')
                wr = WithdrawalRequest.objects.create(
                    wallet=wallet, amount=amount, fee=0, amount_net=amount,
                    payout_method=method, payout_phone=phone, payout_name=name,
                )
                wallet.reserve(wr.amount, description=f"Réservation reversement {wr.reference}", reference=wr.reference)

            # Notifier l'admin
            from apps.notifications.models import AdminNotification
            AdminNotification.objects.create(
                type='fraud_alert',
                title='Nouvelle demande de reversement',
                message=f"{request.user.get_full_name()} demande {wr.amount} FCFA via {wr.get_payout_method_display()}.\nRéférence : {wr.reference}",
                reference=wr.reference,
            )

            # Audit log — création de la demande de reversement
            from .models import AuditLog
            from .services import log_action, get_client_ip
            log_action(
                action=AuditLog.Action.PAYOUT_REQUESTED,
                description=f"Demande reversement {wr.amount} FCFA via {wr.get_payout_method_display()}",
                user=request.user,
                obj=wr,
                metadata={'amount': str(wr.amount), 'payout_method': wr.payout_method},
                ip_address=get_client_ip(request),
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
                        phone_number=request.user.phone_number,
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
    """Exporte la liste complète des participants en CSV."""
    event = get_object_or_404(Event, slug=slug, organizer=request.user)

    tickets = Ticket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=Order.Status.PAID,
    ).select_related(
        'order_item__ticket_type',
        'order_item__order__buyer',
    )

    guest_tickets = GuestTicket.objects.filter(
        order_item__ticket_type__event=event,
        order_item__order__status=GuestOrder.Status.PAID,
    ).select_related(
        'order_item__ticket_type',
        'order_item__order',
    )

    participants_list = []

    for ticket in tickets:
        buyer = ticket.order_item.order.buyer
        participants_list.append({
            'buyer_name': buyer.get_full_name(),
            'buyer_email': buyer.email,
            'buyer_phone': buyer.phone_number or '',
            'ticket_type': ticket.order_item.ticket_type.name,
            'ticket_number': ticket.ticket_number,
            'status': ticket.get_status_display(),
            'created_at': ticket.created_at,
        })

    for ticket in guest_tickets:
        order = ticket.order_item.order
        participants_list.append({
            'buyer_name': order.buyer_name,
            'buyer_email': order.email,
            'buyer_phone': order.phone or '',
            'ticket_type': ticket.order_item.ticket_type.name,
            'ticket_number': ticket.ticket_number,
            'status': ticket.get_status_display(),
            'created_at': ticket.created_at,
        })

    participants_list.sort(
        key=lambda participant: participant['created_at'],
        reverse=True
    )

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="participants_{event.slug}.csv"'
    )
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow([
        'Nom complet',
        'Email',
        'Téléphone',
        'Type de billet',
        'Numéro ticket',
        'Statut',
        'Date achat',
    ])

    for participant in participants_list:
        writer.writerow([
            participant['buyer_name'],
            participant['buyer_email'],
            participant['buyer_phone'],
            participant['ticket_type'],
            participant['ticket_number'],
            participant['status'],
            participant['created_at'].strftime('%d/%m/%Y %H:%M'),
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

import hmac

from django.db import transaction
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render


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

        with transaction.atomic():
            otp = ReversalOTP.objects.select_for_update().get(pk=otp.pk)

            if not otp.is_valid:
                messages.error(request, "Code expiré. Refaites votre demande.")
                return redirect('dashboard:wallet')

            if hmac.compare_digest(code, otp.code):
                otp.is_used = True
                otp.save(update_fields=['is_used'])
                from .services import log_action
                log_action(
                    action=AuditLog.Action.PAYOUT_OTP_VALIDATED,
                    description=f"OTP validé pour le reversement {withdrawal.reference}",
                    user=request.user, obj=withdrawal,
                    metadata={'amount': str(withdrawal.amount), 'payout_method': withdrawal.payout_method},
                )
                withdrawal.status = WithdrawalRequest.Status.PROCESSING
                withdrawal.save(update_fields=['status'])
                from .tasks import process_payout
                process_payout.delay(withdrawal.pk)
                messages.success(request, f"✅ Demande {withdrawal.reference} validée. Reversement en cours automatiquement.")
                return redirect('dashboard:wallet')

            otp.attempts += 1

            if otp.attempts >= 3:
                otp.is_used = True
                otp.save(update_fields=['attempts', 'is_used'])

                withdrawal.status = WithdrawalRequest.Status.REJECTED
                withdrawal.admin_note = "OTP incorrect 3 fois — demande rejetée automatiquement"
                withdrawal.save(update_fields=['status', 'admin_note'])
                withdrawal.wallet.release_reserved(
                    withdrawal.amount,
                    description=f"Libération après rejet OTP {withdrawal.reference}",
                    reference=withdrawal.reference,
                )

                messages.error(request, "❌ 3 tentatives échouées. Demande rejetée. Soumettez une nouvelle demande.")
                return redirect('dashboard:wallet')

            otp.save(update_fields=['attempts'])
            remaining = 3 - otp.attempts
            messages.error(request, f"Code incorrect. {remaining} tentative(s) restante(s).")

    return render(request, 'dashboard/verify_otp.html', {'withdrawal': withdrawal})

@decorators.csrf.csrf_exempt
def paydunya_payout_webhook(request):
    """Callback PayDunya pour confirmer un décaissement."""
    from django.http import JsonResponse
    from apps.payments.paydunya import PayDunyaService
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    payload = PayDunyaService.parse_disbursement_callback(request)
    if not payload or not PayDunyaService.verify_disbursement_callback(payload):
        return JsonResponse({'success': False, 'error': 'Invalid callback'}, status=400)
    reference = payload.get('disburse_id')
    withdrawal = WithdrawalRequest.objects.filter(reference=reference).first()
    if not withdrawal:
        return JsonResponse({'success': False, 'error': 'Unknown disbursement'}, status=404)
    from .tasks import finalize_payout_from_provider
    finalize_payout_from_provider.delay(withdrawal.pk, payload)
    return JsonResponse({'success': True})


@organizer_required
def audit_log(request):
    """Journal d'audit de l'organisateur."""
    from django.core.paginator import Paginator

    logs = AuditLog.objects.filter(
        user=request.user
    ).order_by('-created_at')

    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'dashboard/audit_log.html', {
        'page_obj': page_obj,
    })


@platform_staff_required
def audit_log_admin(request):
    """
    Journal d'activité global — réservé aux super-admins IvoirPass.
    Contrairement à `audit_log` (organisateur), montre TOUTES les actions
    de la plateforme (paiements, commandes, billets, scans, emails,
    connexions, reversements...), avec recherche et filtres.
    """
    from django.core.paginator import Paginator
    from django.db.models import Q

    logs = AuditLog.objects.select_related('user').all()

    action = request.GET.get('action', '').strip()
    if action:
        logs = logs.filter(action=action)

    model_name = request.GET.get('model', '').strip()
    if model_name:
        logs = logs.filter(model_name=model_name)

    q = request.GET.get('q', '').strip()
    if q:
        logs = logs.filter(
            Q(description__icontains=q) |
            Q(object_id__icontains=q) |
            Q(user__email__icontains=q)
        )

    date_from = request.GET.get('date_from', '').strip()
    if date_from:
        logs = logs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to', '').strip()
    if date_to:
        logs = logs.filter(created_at__date__lte=date_to)

    logs = logs.order_by('-created_at')

    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'dashboard/audit_log_admin.html', {
        'page_obj': page_obj,
        'actions': AuditLog.Action.choices,
        'model_names': (
            AuditLog.objects.exclude(model_name='')
            .order_by('model_name').values_list('model_name', flat=True).distinct()
        ),
        'filters': {
            'action': action, 'model': model_name, 'q': q,
            'date_from': date_from, 'date_to': date_to,
        },
    })


@organizer_required
def export_sales_csv(request):
    """Export CSV des ventes de l'organisateur."""
    from apps.tickets.models import OrderItem
    from apps.store.models import ProductOrder

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="ventes_ivoirpass.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(['Type', 'Référence', 'Date', 'Produit/Événement', 'Quantité', 'Brut', 'Commission', 'Net'])

    # Ventes billetterie
    from apps.tickets.models import GuestOrderItem

    items = OrderItem.objects.filter(
        ticket_type__event__organizer=request.user,
        order__status='paid'
    ).select_related('ticket_type__event', 'order')
    guest_items = GuestOrderItem.objects.filter(
        ticket_type__event__organizer=request.user,
        order__status='paid'
    ).select_related('ticket_type__event', 'order')

    for item in list(items) + list(guest_items):
        rate = float(item.ticket_type.event.commission_rate) / 100
        net = int(float(item.subtotal) * (1 - rate))
        writer.writerow([
            'Billet', item.order.order_number,
            item.order.paid_at.strftime('%d/%m/%Y') if item.order.paid_at else '',
            item.ticket_type.event.title, item.quantity,
            int(item.subtotal), int(float(item.subtotal) * rate), net
        ])

    # Ventes boutique
    store_orders = ProductOrder.objects.filter(
        product__seller=request.user, status='paid'
    ).select_related('product')

    for order in store_orders:
        rate = float(order.product.commission_rate) / 100
        net = int(float(order.subtotal) * (1 - rate))
        writer.writerow([
            'Boutique', order.order_number,
            order.paid_at.strftime('%d/%m/%Y') if order.paid_at else '',
            order.product.name, order.quantity,
            int(order.subtotal), int(float(order.subtotal) * rate), net
        ])

    return response


@organizer_required
def export_sales_excel(request):
    """Export Excel des ventes."""
    from apps.tickets.models import OrderItem
    from apps.store.models import ProductOrder

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ventes"
    ws.append(['Type', 'Référence', 'Date', 'Produit/Événement', 'Quantité', 'Brut (FCFA)', 'Commission', 'Net (FCFA)'])

    from apps.tickets.models import GuestOrderItem

    items = OrderItem.objects.filter(
        ticket_type__event__organizer=request.user, order__status='paid'
    ).select_related('ticket_type__event', 'order')
    guest_items = GuestOrderItem.objects.filter(
        ticket_type__event__organizer=request.user, order__status='paid'
    ).select_related('ticket_type__event', 'order')

    for item in list(items) + list(guest_items):
        rate = float(item.ticket_type.event.commission_rate) / 100
        ws.append([
            'Billet', item.order.order_number,
            item.order.paid_at.strftime('%d/%m/%Y') if item.order.paid_at else '',
            item.ticket_type.event.title, item.quantity,
            int(item.subtotal), int(float(item.subtotal) * rate),
            int(float(item.subtotal) * (1 - rate))
        ])

    store_orders = ProductOrder.objects.filter(
        product__seller=request.user, status='paid'
    ).select_related('product')

    for order in store_orders:
        rate = float(order.product.commission_rate) / 100
        ws.append([
            'Boutique', order.order_number,
            order.paid_at.strftime('%d/%m/%Y') if order.paid_at else '',
            order.product.name, order.quantity,
            int(order.subtotal), int(float(order.subtotal) * rate),
            int(float(order.subtotal) * (1 - rate))
        ])

    # Ajuster les colonnes
    for col in ws.columns:
        max_length = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="ventes_ivoirpass.xlsx"'
    wb.save(response)
    return response


@organizer_required
def export_sales_pdf(request):
    """Export PDF des ventes."""
    from apps.tickets.models import OrderItem
    from apps.store.models import ProductOrder

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 16)
    p.drawString(20*mm, height - 20*mm, "Rapport des ventes - IvoirPass")
    p.setFont("Helvetica", 10)
    p.drawString(20*mm, height - 28*mm, f"Organisateur : {request.user.get_full_name()}")
    p.drawString(20*mm, height - 34*mm, f"Généré le : {timezone.now().strftime('%d/%m/%Y à %H:%M')}")

    y = height - 45*mm
    p.setFont("Helvetica-Bold", 9)
    p.drawString(20*mm, y, "Type")
    p.drawString(50*mm, y, "Référence")
    p.drawString(90*mm, y, "Date")
    p.drawString(120*mm, y, "Produit")
    p.drawString(170*mm, y, "Net (FCFA)")
    y -= 5*mm
    p.line(20*mm, y, width - 20*mm, y)
    y -= 7*mm

    p.setFont("Helvetica", 8)
    total_net = 0

    from apps.tickets.models import GuestOrderItem

    items = OrderItem.objects.filter(
        ticket_type__event__organizer=request.user, order__status='paid'
    ).select_related('ticket_type__event', 'order')
    guest_items = GuestOrderItem.objects.filter(
        ticket_type__event__organizer=request.user, order__status='paid'
    ).select_related('ticket_type__event', 'order')

    for item in list(items) + list(guest_items):
        if y < 30*mm:
            p.showPage()
            y = height - 20*mm
        rate = float(item.ticket_type.event.commission_rate) / 100
        net = int(float(item.subtotal) * (1 - rate))
        total_net += net
        p.drawString(20*mm, y, "Billet")
        p.drawString(50*mm, y, item.order.order_number)
        p.drawString(90*mm, y, item.order.paid_at.strftime('%d/%m/%Y') if item.order.paid_at else '')
        p.drawString(120*mm, y, item.ticket_type.event.title[:25])
        p.drawString(170*mm, y, f"{net:,} FCFA")
        y -= 5*mm

    store_orders = ProductOrder.objects.filter(
        product__seller=request.user, status='paid'
    ).select_related('product')

    for order in store_orders:
        if y < 30*mm:
            p.showPage()
            y = height - 20*mm
        rate = float(order.product.commission_rate) / 100
        net = int(float(order.subtotal) * (1 - rate))
        total_net += net
        p.drawString(20*mm, y, "Boutique")
        p.drawString(50*mm, y, order.order_number)
        p.drawString(90*mm, y, order.paid_at.strftime('%d/%m/%Y') if order.paid_at else '')
        p.drawString(120*mm, y, order.product.name[:25])
        p.drawString(170*mm, y, f"{net:,} FCFA")
        y -= 5*mm

    y -= 5*mm
    p.line(20*mm, y, width - 20*mm, y)
    y -= 8*mm
    p.setFont("Helvetica-Bold", 11)
    p.drawString(120*mm, y, f"Total net : {total_net:,} FCFA")

    p.showPage()
    p.save()
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="ventes_ivoirpass.pdf"'
    return response

def submit_dispute(request):
    """Page publique pour soumettre un litige."""
    if request.method == 'POST':
        dispute = Dispute.objects.create(
            type=request.POST.get('type', 'other'),
            reported_by=request.user if request.user.is_authenticated else None,
            email=request.POST.get('email', ''),
            phone=request.POST.get('phone', ''),
            order_number=request.POST.get('order_number', ''),
            ticket_number=request.POST.get('ticket_number', ''),
            subject=request.POST.get('subject', ''),
            description=request.POST.get('description', ''),
        )

        # Notification aux administrateurs (crée l'entrée AdminNotification
        # ET envoie l'email — un seul appel, plus de doublon en base).
        from apps.notifications.tasks import notify_admins_async

        notify_admins_async.delay(
            notification_type='fraud_alert',
            title=f'Nouveau litige : {dispute.get_type_display()}',
            message=(
                f"Un nouveau litige a été ouvert.\n"
                f"Référence : {dispute.reference}\n"
                f"Type : {dispute.get_type_display()}\n"
                f"Sujet : {dispute.subject}\n"
                f"Email : {dispute.email}\n"
                f"Commande : {dispute.order_number or 'N/A'}\n\n"
                f"Description : {dispute.description[:200]}"
            ),
            reference=dispute.reference,
        )

        messages.success(
            request,
            f"Votre réclamation {dispute.reference} a été enregistrée. "
            "Nous vous contacterons sous 48h."
        )

        return redirect('home')

    return render(request, 'pages/report_problem.html')

# ============================================================
# BACK-OFFICE FINANCIER — Recherche/fiche/export des transactions
# (voir audit technique, Phase 2 de la roadmap)
#
# Contrairement à `export_sales_*` plus haut (ventes d'UN organisateur,
# self-service), ce qui suit est une vue PLATEFORME de toutes les
# transactions (Payment), réservée au personnel IvoirPass
# (Admin/Finance/Support/Auditeur — accès LECTURE SEULE, aucune action de
# modification n'est proposée depuis ces vues).
# ============================================================

def _filtered_payments(request):
    """
    Construit le queryset de paiements filtré selon les paramètres GET —
    partagé entre la vue de liste et les trois exports pour ne jamais avoir
    deux logiques de filtrage qui divergent silencieusement.

    Couvre à la fois la billetterie (order/guest_order) et la boutique
    (product_order/guest_product_order) — cette dernière ne dispose de
    lignes Payment que pour les commandes initiées après l'extension du
    modèle Payment (voir audit) ; les commandes boutique antérieures ne
    remonteront pas ici.
    """
    from apps.payments.models import Payment

    payments = Payment.objects.select_related(
        'order__buyer', 'guest_order',
        'product_order__buyer', 'product_order__product',
        'guest_product_order__product',
    ).prefetch_related(
        'order__items__ticket_type__event__organizer',
        'guest_order__guest_items__ticket_type__event__organizer',
    ).order_by('-created_at')

    filters = {
        'q':         request.GET.get('q', '').strip(),
        'status':    request.GET.get('status', '').strip(),
        'provider':  request.GET.get('provider', '').strip(),
        'date_from': request.GET.get('date_from', '').strip(),
        'date_to':   request.GET.get('date_to', '').strip(),
    }

    q = filters['q']
    if q:
        payments = payments.filter(
            Q(order__order_number__icontains=q) |
            Q(guest_order__order_number__icontains=q) |
            Q(product_order__order_number__icontains=q) |
            Q(guest_product_order__order_number__icontains=q) |
            Q(paydunya_token__icontains=q) |
            Q(paydunya_invoice_token__icontains=q) |
            Q(order__buyer__email__icontains=q) |
            Q(order__buyer__phone_number__icontains=q) |
            Q(guest_order__email__icontains=q) |
            Q(guest_order__phone__icontains=q) |
            Q(product_order__buyer__email__icontains=q) |
            Q(guest_product_order__email__icontains=q) |
            Q(guest_product_order__phone__icontains=q)
        )

    if filters['status']:
        payments = payments.filter(status=filters['status'])

    if filters['provider']:
        payments = payments.filter(provider=filters['provider'])

    if filters['date_from']:
        payments = payments.filter(created_at__date__gte=filters['date_from'])

    if filters['date_to']:
        payments = payments.filter(created_at__date__lte=filters['date_to'])

    return payments, filters


def _payment_row(payment):
    """
    Aplati un Payment + la commande qu'il concerne (billetterie ou boutique,
    compte ou invité) en un dict simple à afficher ou exporter — évite de
    dupliquer cette logique dans le template, le CSV, l'Excel et le PDF.
    Retourne None si le paiement n'a (anormalement) aucune commande liée —
    ne devrait jamais arriver vu la contrainte en base sur Payment, mais on
    reste défensif plutôt que de faire planter tout l'export pour une ligne.
    """
    order = payment.order or payment.guest_order or payment.product_order or payment.guest_product_order
    if order is None:
        return None

    is_store = bool(payment.product_order_id or payment.guest_product_order_id)

    if is_store:
        kind = 'Boutique'
        if payment.product_order_id:
            client_name = order.buyer.get_full_name()
            client_email = order.buyer.email
        else:
            client_name = f"{order.first_name} {order.last_name}"
            client_email = order.email
        product = order.product
        event_label = product.name if product else '—'
        organizer_label = product.seller.get_full_name() if product and product.seller else '—'
        ticket_types = f"{order.quantity}x {product.name}" if product else '—'
        quantity = order.quantity
    else:
        kind = 'Billet'
        if payment.order_id:
            client_name = order.buyer.get_full_name()
            client_email = order.buyer.email
            items = list(order.items.all())
        else:
            client_name = order.buyer_name
            client_email = order.email
            items = list(order.guest_items.all())

        event_label = ', '.join(sorted({
            it.ticket_type.event.title for it in items if it.ticket_type and it.ticket_type.event
        })) or '—'
        organizer_label = ', '.join(sorted({
            it.ticket_type.event.organizer.get_full_name()
            for it in items if it.ticket_type and it.ticket_type.event and it.ticket_type.event.organizer
        })) or '—'
        quantity = sum(it.quantity for it in items)
        ticket_types = ', '.join(f"{it.quantity}x {it.ticket_type.name}" for it in items) if items else '—'

    gross = order.subtotal
    # GuestOrder / commandes boutique ne stockent pas toujours une commission
    # séparée — on la déduit de total - subtotal plutôt que de supposer un
    # champ absent.
    fees = getattr(order, 'commission', None)
    if fees is None:
        fees = order.total - order.subtotal
    net = order.total - fees

    return {
        'payment': payment,
        'order': order,
        'kind': kind,
        'order_number': order.order_number,
        'client_name': client_name or '—',
        'client_email': client_email or '—',
        'event': event_label,
        'organizer': organizer_label,
        'ticket_types': ticket_types,
        'quantity': quantity,
        'gross': gross,
        'fees': fees,
        'net': net,
        'currency': payment.currency,
        'payment_method': order.payment_method or payment.get_provider_display(),
        'status': payment.status,
        'status_display': payment.get_status_display(),
        'paydunya_token': payment.paydunya_token,
        'confirmed_at': payment.completed_at,
        'created_at': payment.created_at,
    }


def _redact_raw_response(raw_response):
    """
    Masque le hash de signature PayDunya avant tout affichage/export —
    même en back-office, ce hash statique ne doit jamais transiter
    inutilement (voir audit R-08 : s'il fuit, il reste valide indéfiniment
    tant que le Master Key n'est pas régénéré).
    """
    if not isinstance(raw_response, dict):
        return raw_response
    redacted = dict(raw_response)
    if 'hash' in redacted:
        redacted['hash'] = '••• (masqué)'
    data = redacted.get('data')
    if isinstance(data, dict) and 'hash' in data:
        data = dict(data)
        data['hash'] = '••• (masqué)'
        redacted['data'] = data
    return redacted


@platform_staff_required
def transactions_list(request):
    """
    Liste plateforme de toutes les transactions, recherchable et filtrable
    (audit section 11). Lecture seule — aucune action de modification n'est
    proposée ici, quel que soit le rôle (voir platform_staff_required).
    """
    from django.core.paginator import Paginator
    from apps.payments.models import Payment

    payments, filters = _filtered_payments(request)

    paginator = Paginator(payments, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    rows = [r for r in (_payment_row(p) for p in page_obj) if r]

    return render(request, 'dashboard/transactions_list.html', {
        'page_obj': page_obj,
        'rows': rows,
        'filters': filters,
        'statuses': Payment.Status.choices,
        'providers': Payment.Provider.choices,
    })


@platform_staff_required
def transaction_detail(request, order_number):
    """
    Fiche détaillée d'une transaction (audit section 10) : résumé, détail
    de la commande, informations PayDunya, chronologie reconstituée à
    partir du Payment/de la commande/du journal d'audit, et actions
    administratives liées.
    """
    import json as _json
    from apps.payments.models import Payment

    payment = Payment.objects.filter(
        Q(order__order_number=order_number) | Q(guest_order__order_number=order_number) |
        Q(product_order__order_number=order_number) | Q(guest_product_order__order_number=order_number)
    ).select_related(
        'order__buyer', 'guest_order', 'product_order__buyer', 'guest_product_order'
    ).first()

    if payment is None:
        messages.error(request, f"Transaction {order_number} introuvable.")
        return redirect('dashboard:transactions')

    row = _payment_row(payment)
    order = row['order']
    is_store = bool(payment.product_order_id or payment.guest_product_order_id)
    if is_store:
        # Une commande boutique porte un seul produit/quantité — pas de
        # lignes multiples comme pour la billetterie, mais le template
        # attend un itérable "items" : on lui fabrique une ligne unique.
        items = [order] if order.product_id else []
    else:
        items = list(order.items.all()) if payment.order_id else list(order.guest_items.all())

    audit_entries = AuditLog.objects.filter(object_id=order_number).order_by('created_at')

    timeline = [{'label': 'Commande créée', 'at': order.created_at}]
    timeline.append({'label': 'Paiement initié', 'at': payment.created_at})
    for entry in audit_entries:
        if entry.action in (
            AuditLog.Action.PAYMENT_SUCCESS, AuditLog.Action.PAYMENT_FAILED,
            AuditLog.Action.TICKET_CREATED, AuditLog.Action.EMAIL_SENT,
            AuditLog.Action.RECONCILIATION_RECOVERED, AuditLog.Action.RECONCILIATION_ANOMALY,
            AuditLog.Action.ORDER_REFUNDED, AuditLog.Action.ORDER_CANCELLED,
        ):
            timeline.append({'label': entry.get_action_display(), 'at': entry.created_at, 'description': entry.description})
    if payment.completed_at:
        timeline.append({'label': 'Paiement confirmé (PayDunya)', 'at': payment.completed_at})
    timeline.sort(key=lambda t: t['at'])

    raw_response = _redact_raw_response(payment.raw_response)

    return render(request, 'dashboard/transaction_detail.html', {
        'row': row,
        'payment': payment,
        'order': order,
        'items': items,
        'timeline': timeline,
        'audit_entries': audit_entries,
        'raw_response_json': _json.dumps(raw_response, indent=2, ensure_ascii=False, default=str) if raw_response else None,
    })


def _export_metadata_lines(request, filters, count, total_gross, total_fees, total_net, currency):
    """
    Métadonnées obligatoires sur tout export financier (audit section 12) :
    période, date de génération, utilisateur, filtres utilisés, totaux.
    """
    period = f"Du {filters['date_from']} au {filters['date_to']}" if (filters['date_from'] or filters['date_to']) else "Toute la période"
    active_filters = ', '.join(f"{k}={v}" for k, v in filters.items() if v) or 'Aucun'
    return [
        ['Période', period],
        ['Généré le', timezone.now().strftime('%d/%m/%Y à %H:%M')],
        ['Généré par', request.user.email],
        ['Filtres appliqués', active_filters],
        ['Nombre de transactions', str(count)],
        ['Total brut', f"{int(total_gross):,} {currency}".replace(',', ' ')],
        ['Total frais', f"{int(total_fees):,} {currency}".replace(',', ' ')],
        ['Total net', f"{int(total_net):,} {currency}".replace(',', ' ')],
    ]


@platform_staff_required
def export_transactions_csv(request):
    from .services import log_action, get_client_ip
    payments, filters = _filtered_payments(request)
    rows = [r for r in (_payment_row(p) for p in payments) if r]

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions_ivoirpass.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)

    writer.writerow(['Date', 'Type', 'Référence', 'Réf. PayDunya', 'Client', 'Email', 'Événement/Produit', 'Organisateur/Vendeur',
                      'Détail', 'Qté', 'Brut', 'Frais', 'Net', 'Devise', 'Moyen de paiement',
                      'Statut', 'Date confirmation'])
    total_gross = total_fees = total_net = 0
    for r in rows:
        writer.writerow([
            r['created_at'].strftime('%d/%m/%Y %H:%M'), r['kind'], r['order_number'], r['paydunya_token'],
            r['client_name'], r['client_email'], r['event'], r['organizer'], r['ticket_types'],
            r['quantity'], int(r['gross']), int(r['fees']), int(r['net']), r['currency'],
            r['payment_method'], r['status_display'],
            r['confirmed_at'].strftime('%d/%m/%Y %H:%M') if r['confirmed_at'] else '',
        ])
        total_gross += r['gross']; total_fees += r['fees']; total_net += r['net']

    writer.writerow([])
    currency = rows[0]['currency'] if rows else 'XOF'
    for label, value in _export_metadata_lines(request, filters, len(rows), total_gross, total_fees, total_net, currency):
        writer.writerow([label, value])

    log_action(action=AuditLog.Action.EXPORT, description="Export CSV des transactions (back-office)",
               user=request.user, model_name='Payment', metadata={'count': len(rows), 'filters': filters},
               ip_address=get_client_ip(request))
    return response


@platform_staff_required
def export_transactions_excel(request):
    from .services import log_action, get_client_ip
    payments, filters = _filtered_payments(request)
    rows = [r for r in (_payment_row(p) for p in payments) if r]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(['Date', 'Type', 'Référence', 'Réf. PayDunya', 'Client', 'Email', 'Événement/Produit', 'Organisateur/Vendeur',
                'Détail', 'Qté', 'Brut', 'Frais', 'Net', 'Devise', 'Moyen de paiement',
                'Statut', 'Date confirmation'])
    total_gross = total_fees = total_net = 0
    for r in rows:
        ws.append([
            r['created_at'].strftime('%d/%m/%Y %H:%M'), r['kind'], r['order_number'], r['paydunya_token'],
            r['client_name'], r['client_email'], r['event'], r['organizer'], r['ticket_types'],
            r['quantity'], int(r['gross']), int(r['fees']), int(r['net']), r['currency'],
            r['payment_method'], r['status_display'],
            r['confirmed_at'].strftime('%d/%m/%Y %H:%M') if r['confirmed_at'] else '',
        ])
        total_gross += r['gross']; total_fees += r['fees']; total_net += r['net']

    ws.append([])
    currency = rows[0]['currency'] if rows else 'XOF'
    for label, value in _export_metadata_lines(request, filters, len(rows), total_gross, total_fees, total_net, currency):
        ws.append([label, value])

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="transactions_ivoirpass.xlsx"'
    wb.save(response)

    log_action(action=AuditLog.Action.EXPORT, description="Export Excel des transactions (back-office)",
               user=request.user, model_name='Payment', metadata={'count': len(rows), 'filters': filters},
               ip_address=get_client_ip(request))
    return response


@platform_staff_required
def export_transactions_pdf(request):
    from .services import log_action, get_client_ip
    payments, filters = _filtered_payments(request)
    rows = [r for r in (_payment_row(p) for p in payments) if r]

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 14)
    p.drawString(15*mm, height - 15*mm, "Rapport des transactions — IvoirPass (back-office)")
    p.setFont("Helvetica", 8)
    p.drawString(15*mm, height - 21*mm, f"Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')} par {request.user.email}")

    total_gross = total_fees = total_net = 0
    y = height - 30*mm
    p.setFont("Helvetica-Bold", 7)
    p.drawString(15*mm, y, "Date | Type | Réf. | Client | Événement/Produit | Qté | Brut | Frais | Net | Statut")
    y -= 5*mm
    p.setFont("Helvetica", 7)
    for r in rows:
        if y < 20*mm:
            p.showPage()
            p.setFont("Helvetica", 7)
            y = height - 15*mm
        line = f"{r['created_at'].strftime('%d/%m/%y')} | {r['kind']} | {r['order_number']} | {r['client_name'][:20]} | {r['event'][:20]} | {r['quantity']} | {int(r['gross'])} | {int(r['fees'])} | {int(r['net'])} | {r['status_display']}"
        p.drawString(15*mm, y, line[:140])
        y -= 4.5*mm
        total_gross += r['gross']; total_fees += r['fees']; total_net += r['net']

    if y < 40*mm:
        p.showPage()
        y = height - 15*mm
    y -= 6*mm
    p.setFont("Helvetica-Bold", 8)
    currency = rows[0]['currency'] if rows else 'XOF'
    for label, value in _export_metadata_lines(request, filters, len(rows), total_gross, total_fees, total_net, currency):
        p.drawString(15*mm, y, f"{label} : {value}")
        y -= 4.5*mm

    p.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="transactions_ivoirpass.pdf"'

    log_action(action=AuditLog.Action.EXPORT, description="Export PDF des transactions (back-office)",
               user=request.user, model_name='Payment', metadata={'count': len(rows), 'filters': filters},
               ip_address=get_client_ip(request))
    return response
