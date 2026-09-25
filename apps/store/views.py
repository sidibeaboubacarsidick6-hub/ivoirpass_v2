"""
IvoirPass V2 — Vues de la boutique culturelle
"""
from django.core.cache import cache
from django_ratelimit.decorators import ratelimit
import os
import json
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Product, ProductCategory, ProductOrder, DownloadLink
from .models import GuestProductOrder, GuestDownloadLink
from .forms import ProductForm
from apps.dashboard.models import AuditLog
from apps.dashboard.services import log_action, get_client_ip

logger = logging.getLogger(__name__)


# ============================================================
# ✅ CORRECTIF AUDIT — H-2 : confirmation boutique invité robuste
# face à un stock devenu insuffisant entre la création de la
# commande et la confirmation du paiement.
#
# GuestProductOrder.mark_as_paid() lève une ValueError si le stock
# physique manque au moment de décrémenter (voir apps/store/models.py).
# Avant ce correctif :
#   - guest_store_payment_return : l'exception n'était pas interceptée
#     -> 500 renvoyée à un client qui vient de payer.
#   - guest_store_webhook : l'exception était avalée par un
#     `except Exception` générique -> silence total, PayDunya reçoit
#     quand même "OK" (pas de retry), personne n'est alerté.
#   - reconcile_pending_payments (apps/payments/tasks.py) : replante à
#     chaque exécution (toutes les 20 min) sur la même commande.
#
# Ce helper centralise la confirmation : en cas de ValueError, il trace
# une AuditLog dédiée (paiement encaissé, stock indisponible) et alerte
# les admins par email immédiatement, au lieu de laisser planter ou
# disparaître silencieusement l'incident.
# ============================================================
def _confirm_guest_product_order_safely(order, token, raw_data, source):
    """
    Tente de confirmer une GuestProductOrder après paiement PayDunya.

    Args:
        order: la GuestProductOrder à confirmer.
        token: le token PayDunya du paiement.
        raw_data: la réponse brute PayDunya (pour le Payment.raw_response).
        source: 'retour' ou 'webhook' — uniquement pour le message d'audit.

    Returns:
        (newly_confirmed: bool, stock_conflict: bool)
        - newly_confirmed=True  : commande confirmée par cet appel.
        - newly_confirmed=False, stock_conflict=False : déjà confirmée par
          un appel concurrent (cas normal d'idempotence).
        - newly_confirmed=False, stock_conflict=True : paiement réellement
          encaissé par PayDunya, mais stock insuffisant — nécessite une
          intervention humaine (remboursement ou réapprovisionnement).
    """
    try:
        newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference=token)
    except ValueError as e:
        logger.error(
            f"[H-2] Commande boutique invité {order.order_number} payée chez "
            f"PayDunya mais non confirmable ({source}) : {e}"
        )
        log_action(
            action=AuditLog.Action.PAYMENT_PAID_STOCK_UNAVAILABLE,
            description=(
                f"Paiement PayDunya encaissé pour la commande boutique invité "
                f"{order.order_number}, mais confirmation impossible ({source}) : "
                f"stock produit insuffisant. Intervention manuelle requise "
                f"(remboursement ou réapprovisionnement)."
            ),
            model_name='GuestProductOrder', object_id=order.order_number,
            metadata={
                'paydunya_token': token,
                'amount': str(order.total),
                'product': order.product.name,
                'quantity': order.quantity,
                'error': str(e)[:200],
            },
        )
        _alert_admins_stock_conflict(order, token)
        return False, True

    if newly_confirmed:
        from apps.payments.models import Payment
        Payment.objects.filter(guest_product_order=order).update(
            status=Payment.Status.COMPLETED, raw_response=raw_data,
            completed_at=timezone.now(),
        )
        log_action(
            action=AuditLog.Action.PAYMENT_SUCCESS,
            description=f"Paiement confirmé ({source}) pour la commande boutique invité {order.order_number}",
            model_name='GuestProductOrder', object_id=order.order_number,
            metadata={'provider': 'paydunya', 'amount': str(order.total)},
        )
    return newly_confirmed, False


def _alert_admins_stock_conflict(order, token):
    """
    Alerte immédiate des admins — même patron que
    apps.payments.tasks._send_anomaly_alert — dès qu'un paiement encaissé
    ne peut pas être confirmé faute de stock. Best-effort : ne doit jamais
    faire planter la confirmation elle-même.
    """
    try:
        from django.conf import settings
        from django.core.mail import send_mail
        from apps.accounts.models import CustomUser

        admins = CustomUser.objects.filter(
            role=CustomUser.Role.ADMIN, is_active=True, notify_email=True,
        )
        recipient_list = list(admins.values_list('email', flat=True))
        if not recipient_list:
            logger.warning("[H-2] Conflit stock/paiement mais aucun admin à notifier (notify_email=False ?)")
            return

        send_mail(
            subject=f"[IvoirPass] ⚠️ Payé mais stock indisponible — {order.order_number}",
            message=(
                f"La commande boutique invité {order.order_number} a été payée "
                f"({order.total} XOF, token PayDunya {token}) mais ne peut pas être "
                f"confirmée : stock insuffisant pour « {order.product.name} ».\n\n"
                f"Action requise : rembourser le client ou réapprovisionner puis "
                f"confirmer manuellement depuis le back-office.\n\n"
                f"Client : {order.buyer_name} <{order.email}>"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"[H-2] Échec envoi alerte conflit stock/paiement pour {order.order_number}: {e}")


# ============================================
# VUES PUBLIQUES
# ============================================

def store_list(request):
    """Boutique publique — liste de tous les produits."""
    # 🔥 Cache par query string (5 minutes)
    query = request.GET.get('q', '')
    category_slug = request.GET.get('category', '')
    product_type = request.GET.get('type', '')
    sort = request.GET.get('sort', '-created_at')
    page_number = request.GET.get('page', 1)

    cache_key = f'store_list_{query}_{category_slug}_{product_type}_{sort}_page_{page_number}'
    cached_data = cache.get(cache_key)

    if cached_data is not None:
        return render(request, 'store/list.html', cached_data)

    products = Product.objects.filter(
        status=Product.Status.PUBLISHED
    ).select_related('category', 'seller')

    if query:
        products = products.filter(
            Q(name__icontains=query)         |
            Q(author__icontains=query)       |
            Q(description__icontains=query)  |
            Q(tags__icontains=query)
        )

    if category_slug:
        products = products.filter(category__slug=category_slug)

    if product_type:
        products = products.filter(product_type=product_type)

    if sort in ['-created_at', 'price', '-price', '-sold_count']:
        products = products.order_by(sort)

    paginator   = Paginator(products, 12)
    page_obj    = paginator.get_page(page_number)

    categories = ProductCategory.objects.filter(is_active=True)

    context = {
        'page_obj':     page_obj,
        'categories':   categories,
        'query':        query,
        'category_slug': category_slug,
        'product_type': product_type,
        'sort':         sort,
        'total':        paginator.count,
        'product_types': Product.ProductType.choices,
    }

    cache.set(cache_key, context, 300)
    return render(request, 'store/list.html', context)


def store_detail(request, slug):
    """Page détail d'un produit."""
    product = get_object_or_404(
        Product.objects.select_related('category', 'seller'),
        slug=slug,
        status=Product.Status.PUBLISHED
    )

    # Produits similaires
    similar = Product.objects.filter(
        status=Product.Status.PUBLISHED,
        category=product.category
    ).exclude(pk=product.pk).order_by('-sold_count')[:4]

    # L'utilisateur a-t-il déjà acheté ce produit ?
    already_purchased = False
    download_links    = []
    if request.user.is_authenticated:
        order = ProductOrder.objects.filter(
            buyer=request.user,
            product=product,
            status=ProductOrder.Status.PAID
        ).first()
        if order:
            already_purchased = True
            download_links    = order.download_links.filter(
                expires_at__gt=timezone.now()
            )

    return render(request, 'store/detail.html', {
        'product':           product,
        'similar':           similar,
        'already_purchased': already_purchased,
        'download_links':    download_links,
    })


@login_required
def my_orders(request):
    """
    Achat "avec compte" retiré (audit H-3) : le tunnel d'achat boutique
    passe désormais uniquement par l'achat invité (guest_buy_product /
    GuestProductOrder). Cette vue reste une simple redirection car elle
    est encore référencée par le lien "Commandes boutique" du menu
    vendeur (templates/dashboard/base_dashboard.html).
    """
    return redirect('home')


@login_required
def download_file(request, token):
    """
    Achat "avec compte" retiré (audit H-3) : conservée en simple
    redirection car référencée par templates/store/detail.html (section
    "déjà acheté") et templates/pages/my_orders_history.html. Le
    téléchargement des achats invité passe par guest_download_file /
    GuestDownloadLink.
    """
    return redirect('home')


# ============================================
# VUES VENDEUR
# ============================================

def seller_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_organizer or request.user.is_platform_admin):
            messages.error(
                request,
                "Cette section est réservée aux vendeurs."
            )
            return redirect('store:list')
        return view_func(request, *args, **kwargs)
    return wrapper


@seller_required
def my_products(request):
    """Liste des produits du vendeur."""
    products = Product.objects.filter(
        seller=request.user
    ).order_by('-created_at')

    stats = {
        'total':     products.count(),
        'published': products.filter(
            status=Product.Status.PUBLISHED
        ).count(),
        'total_sold': sum(p.sold_count for p in products),
    }

    return render(request, 'store/my_products.html', {
        'products': products,
        'stats':    stats,
    })


@seller_required
def product_stats(request, slug):
    """Statistiques detaillees d'un produit boutique (comparable a event_stats)."""
    from decimal import Decimal
    from django.db.models import Sum
    from datetime import timedelta

    product = get_object_or_404(Product, slug=slug, seller=request.user)

    orders = GuestProductOrder.objects.filter(
        product=product, status=GuestProductOrder.Status.PAID
    ).order_by('-paid_at')

    gross_revenue = orders.aggregate(t=Sum('subtotal'))['t'] or 0
    units_sold    = orders.aggregate(t=Sum('quantity'))['t'] or 0

    commission_rate = Decimal(str(product.commission_rate)) / Decimal('100')
    gross_decimal   = Decimal(str(gross_revenue))
    commission      = gross_decimal * commission_rate
    net_revenue     = gross_decimal - commission

    # Repartition par format choisi (surtout utile pour les bundles)
    format_stats = []
    for method_value, method_label in GuestProductOrder.DeliveryMethod.choices:
        method_orders = orders.filter(delivery_method=method_value)
        count = method_orders.count()
        if count:
            format_stats.append({
                'label':   method_label,
                'count':   count,
                'revenue': method_orders.aggregate(t=Sum('subtotal'))['t'] or 0,
            })

    # Telechargements (produits numeriques/bundle)
    download_links  = GuestDownloadLink.objects.filter(product=product)
    downloads_used  = download_links.aggregate(t=Sum('download_count'))['t'] or 0
    downloads_total = download_links.aggregate(t=Sum('max_downloads'))['t'] or 0

    # Commandes recentes
    recent_orders = orders[:20]

    # Timeline des ventes (30 derniers jours)
    sales_timeline = []
    today = timezone.now().date()
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_qty = orders.filter(paid_at__date=day).aggregate(t=Sum('quantity'))['t'] or 0
        sales_timeline.append({'date': day.strftime('%d/%m'), 'qty': day_qty})

    return render(request, 'store/product_stats.html', {
        'product':          product,
        'gross_revenue':    gross_revenue,
        'commission':       commission,
        'net_revenue':      net_revenue,
        'units_sold':       units_sold,
        'orders_count':     orders.count(),
        'format_stats':     format_stats,
        'downloads_used':   downloads_used,
        'downloads_total':  downloads_total,
        'recent_orders':    recent_orders,
        'sales_timeline':   sales_timeline,
    })


@seller_required
def product_buyers(request, slug):
    """
    Liste complète des acheteurs d'un produit — recherche/filtrage,
    export CSV et impression. Même patron que la liste des participants
    d'un événement (apps/dashboard/views.py:participants).
    """
    product = get_object_or_404(Product, slug=slug, seller=request.user)

    orders = GuestProductOrder.objects.filter(
        product=product, status=GuestProductOrder.Status.PAID
    ).order_by('-paid_at')

    search = request.GET.get('q', '').strip()
    delivery_filter = request.GET.get('delivery', '').strip()

    if search:
        orders = orders.filter(
            Q(first_name__icontains=search) | Q(last_name__icontains=search) |
            Q(email__icontains=search) | Q(phone__icontains=search) |
            Q(order_number__icontains=search)
        )

    if delivery_filter:
        orders = orders.filter(delivery_method=delivery_filter)

    return render(request, 'store/product_buyers.html', {
        'product': product,
        'orders': orders,
        'search': search,
        'delivery_filter': delivery_filter,
        'total_count': orders.count(),
    })


@seller_required
def export_product_buyers_csv(request, slug):
    """Exporte la liste complète des acheteurs d'un produit en CSV."""
    import csv

    product = get_object_or_404(Product, slug=slug, seller=request.user)
    orders = GuestProductOrder.objects.filter(
        product=product, status=GuestProductOrder.Status.PAID
    ).order_by('-paid_at')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="acheteurs_{product.slug}.csv"'
    response.write('﻿')
    writer = csv.writer(response)
    writer.writerow(['Commande', 'Nom', 'Email', 'Téléphone', 'Format', 'Qté', 'Montant', 'Date'])
    for order in orders:
        writer.writerow([
            order.order_number, order.buyer_name, order.email, order.phone,
            order.get_delivery_method_display(), order.quantity,
            int(order.total), order.paid_at.strftime('%d/%m/%Y %H:%M') if order.paid_at else '',
        ])

    log_action(
        action=AuditLog.Action.EXPORT,
        description=f"Export CSV des acheteurs — {product.name}",
        user=request.user, model_name='GuestProductOrder',
        metadata={'product': product.name, 'count': orders.count()},
        ip_address=get_client_ip(request),
    )
    return response


@seller_required
def product_create(request):
    """Créer un nouveau produit."""
    form = ProductForm()

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product        = form.save(commit=False)
            product.seller = request.user
            product.save()
            messages.success(
                request,
                f"Produit « {product.name} » créé avec succès !"
            )
            return redirect('store:my_products')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'store/product_form.html', {
        'form':   form,
        'action': 'Créer',
    })


@seller_required
def product_edit(request, slug):
    """Modifier un produit existant."""
    product = get_object_or_404(
        Product, slug=slug, seller=request.user
    )
    form = ProductForm(instance=product)

    if request.method == 'POST':
        form = ProductForm(
            request.POST, request.FILES, instance=product
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Produit mis à jour.")
            return redirect('store:my_products')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'store/product_form.html', {
        'form':    form,
        'product': product,
        'action':  'Modifier',
    })


@seller_required
def product_delete(request, slug):
    """Supprime ou archive un produit."""
    product = get_object_or_404(
        Product, slug=slug, seller=request.user
    )
    if request.method == 'POST':
        if product.sold_count > 0:
            product.status = Product.Status.ARCHIVED
            product.save()
            messages.warning(
                request,
                f"Produit « {product.name} » archivé "
                f"(des ventes existent)."
            )
        else:
            name = product.name
            product.delete()
            messages.success(request, f"Produit « {name} » supprimé.")
    return redirect('store:my_products')


@csrf_exempt
@require_POST
@ratelimit(key='ip', rate='30/m', block=True)
def store_webhook(request):
    """Webhook PayDunya pour les commandes boutique."""
    from django.db import transaction

    if not request.body:
        logger.warning("Store webhook: body vide")
        return HttpResponse('OK', status=200)

    # 🔒 VÉRIFICATION SIGNATURE PAYDUNYA
    from apps.payments.paydunya import PayDunyaService
    if not PayDunyaService.verify_webhook_signature(request):
        logger.error("Store webhook rejeté : signature PayDunya invalide")
        return HttpResponse('FORBIDDEN', status=403)

    try:
        raw_data = json.loads(request.body)
        logger.info(f"Store webhook raw data: {raw_data}")

        if 'data' in raw_data:
            payload = raw_data['data']
        else:
            payload = raw_data

        invoice = payload.get('invoice', {})
        custom_data = payload.get('custom_data', {})

        status = invoice.get('status', '')
        token = invoice.get('invoiceToken', '') or payload.get('token', '')
        order_number = custom_data.get('store_order_number', '')

        logger.info(f"Store webhook: order={order_number}, status={status}, token={token}")

        # 🔒 Vérification serveur-à-serveur via l'API PayDunya
        if token and status == 'completed':
            result = PayDunyaService.verify_payment(token)
            if result.get('status') != 'completed':
                logger.warning(f"Store webhook: paiement non confirmé par API - {token}")
                return HttpResponse('OK', status=200)

        if status == 'completed' and order_number:
            try:
                # Verrouille la ligne commande pour rester robuste face aux
                # retries de webhook PayDunya (deux livraisons quasi
                # simultanées ne doivent confirmer/décrémenter le stock
                # qu'une seule fois) — même patron que pour les commandes
                # de billetterie (apps/tickets/models.py mark_as_paid).
                with transaction.atomic():
                    order = ProductOrder.objects.select_for_update().get(
                        order_number=order_number,
                        status=ProductOrder.Status.PENDING
                    )

                    order.status = ProductOrder.Status.PAID
                    order.payment_method = 'paydunya'
                    order.payment_reference = token
                    order.paid_at = timezone.now()
                    order.save()

                    if order.product.is_physical:
                        order.product.stock -= order.quantity
                        order.product.sold_count += order.quantity
                        order.product.save(update_fields=['stock', 'sold_count'])

                logger.info(f"Store webhook: commande {order_number} validée")

                try:
                    order._credit_seller_wallet()
                except Exception as e:
                    logger.error(f"Store webhook: erreur wallet: {e}")

                if order.product.is_digital:
                    from .models import DownloadLink
                    if not DownloadLink.objects.filter(order=order).exists():
                        order._generate_download_links()
                        try:
                            from apps.notifications.tasks import send_download_link_email_async
                            send_download_link_email_async.delay(str(order.uuid))
                        except Exception as e:
                            logger.error(f"Store webhook: erreur envoi email: {e}")

            except ProductOrder.DoesNotExist:
                logger.warning(f"Store webhook: commande {order_number} introuvable ou déjà payée")
            except Exception as e:
                logger.error(f"Store webhook: erreur mise à jour: {e}")

        return HttpResponse('OK', status=200)

    except json.JSONDecodeError as e:
        logger.error(f"Store webhook: JSON invalide - {e}, body: {request.body[:200]}")
        return HttpResponse('OK', status=200)
    except Exception as e:
        logger.error(f"Store webhook error: {e}")
        return HttpResponse('OK', status=200)


# ============================================
# ACHAT BOUTIQUE SANS COMPTE (GUEST)
# ============================================

def guest_buy_product(request, slug):
    """
    Achat sans compte — formulaire dynamique selon le type de produit.
    Le client peut acheter le même produit autant de fois qu'il veut.
    """
    product = get_object_or_404(Product, slug=slug, status=Product.Status.PUBLISHED)

    if not product.is_available:
        messages.error(request, "Ce produit n'est plus disponible.")
        return redirect('store:detail', slug=slug)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name',  '').strip()
        email      = request.POST.get('email',      '').strip()
        phone      = request.POST.get('phone',      '').strip()
        quantity   = int(request.POST.get('quantity', 1))
        delivery_method = request.POST.get(
            'delivery_method',
            'download' if product.is_digital else 'delivery'
        )

        errors = []
        if not first_name: errors.append("Le prénom est requis.")
        if not last_name:  errors.append("Le nom est requis.")
        if not email:      errors.append("L'email est requis.")

        # Adresse obligatoire si livraison physique (seule ou en bundle)
        if delivery_method in ('delivery', 'both'):
            delivery_name    = request.POST.get('delivery_name', '').strip()
            delivery_phone   = request.POST.get('delivery_phone', '').strip()
            delivery_address = request.POST.get('delivery_address', '').strip()
            delivery_city    = request.POST.get('delivery_city', '').strip()
            if not delivery_name:    errors.append("Le nom du destinataire est requis.")
            if not delivery_phone:   errors.append("Le téléphone de livraison est requis.")
            if not delivery_address: errors.append("L'adresse est requise.")
            if not delivery_city:    errors.append("La ville est requise.")

        if delivery_method in ('delivery', 'both') and quantity > product.stock:
            errors.append("Quantité demandée supérieure au stock disponible.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'store/guest_checkout.html', {'product': product})

        # Calcul montants — pour un bundle, le prix depend du format choisi
        if product.product_type == Product.ProductType.BUNDLE:
            if delivery_method == 'download':
                unit_price = product.price_digital
            elif delivery_method == 'delivery':
                unit_price = product.price_physical
            else:
                unit_price = product.price
            if not unit_price:
                messages.error(request, "Ce format n'est pas disponible pour ce produit.")
                return render(request, 'store/guest_checkout.html', {'product': product})
        else:
            unit_price = product.price
        subtotal = unit_price * quantity
        total    = subtotal  # Commission prélevée sur le vendeur, pas sur l'acheteur

        # 🔒 Verrouillage du stock pour éviter les race conditions
        from django.db import transaction

        with transaction.atomic():
            product_locked = Product.objects.select_for_update().get(pk=product.pk)

            if delivery_method in ('delivery', 'both') and product_locked.stock < quantity:
                messages.error(request, "Stock insuffisant. Réessayez.")
                return render(request, 'store/guest_checkout.html', {'product': product})

            order = GuestProductOrder.objects.create(
                first_name = first_name,
                last_name  = last_name,
                email      = email,
                phone      = phone,
                product    = product_locked,
                quantity   = quantity,
                unit_price = unit_price,
                subtotal   = subtotal,
                total      = total,
                delivery_method = delivery_method,
                status = GuestProductOrder.Status.PENDING,
            )

        if delivery_method in ('delivery', 'both'):
            order.delivery_name         = request.POST.get('delivery_name', '').strip()
            order.delivery_phone        = request.POST.get('delivery_phone', '').strip()
            order.delivery_address      = request.POST.get('delivery_address', '').strip()
            order.delivery_city         = request.POST.get('delivery_city', '').strip()
            order.delivery_commune      = request.POST.get('delivery_commune', '').strip()
            order.delivery_country      = request.POST.get('delivery_country', "Côte d'Ivoire").strip()
            order.delivery_instructions = request.POST.get('delivery_instructions', '').strip()
            order.save()

        log_action(
            action=AuditLog.Action.ORDER_CREATED,
            description=f"Commande boutique invité {order.order_number} créée ({email})",
            model_name='GuestProductOrder', object_id=order.order_number,
            metadata={'total': str(total), 'product': product.name, 'quantity': quantity},
            ip_address=get_client_ip(request),
        )

        return redirect('store:guest_payment', order_number=order.order_number)

    return render(request, 'store/guest_checkout.html', {'product': product})


def guest_store_payment_initiate(request, order_number):
    """Initie le paiement PayDunya pour une commande boutique invité."""
    from django.conf import settings
    import requests as req

    order = get_object_or_404(GuestProductOrder, order_number=order_number)

    if order.status == GuestProductOrder.Status.PAID:
        return redirect('store:guest_confirmation', order_number=order_number)

    base_url    = settings.PAYDUNYA_BASE_URL
    return_url  = f"{base_url}/boutique/guest/retour/{order.order_number}/"
    cancel_url  = f"{base_url}/boutique/guest/annulation/{order.order_number}/"
    webhook_url = f"{base_url}/boutique/guest/webhook/"

    payload = {
        "store": {
            "name": "IvoirPass Boutique",
            "tagline": "Culture ivoirienne",
            "website_url": base_url,
        },
        "invoice": {
            "items": {
                "item_1": {
                    "name": order.product.name,
                    "quantity": order.quantity,
                    "unit_price": str(order.unit_price),
                    "total_price": str(order.subtotal),
                    "description": order.product.get_product_type_display(),
                }
            },
            "total_amount": str(int(order.total)),
            "description": f"Commande boutique {order.order_number}",
        },
        "actions": {
            "cancel_url": cancel_url,
            "return_url": return_url,
            "callback_url": webhook_url,
        },
        "custom_data": {
            "guest_store_order_number": order.order_number,
            "buyer_email": order.email,
        }
    }

    headers = {
        'Content-Type': 'application/json',
        'PAYDUNYA-MASTER-KEY': settings.PAYDUNYA_MASTER_KEY,
        'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
        'PAYDUNYA-TOKEN': settings.PAYDUNYA_TOKEN,
    }

    try:
        response = req.post(
            settings.PAYDUNYA_API_BASE + '/checkout-invoice/create',
            json=payload, headers=headers, timeout=30
        )
        data = response.json()

        if data.get('response_code') == '00':
            token = data['token']
            request.session[f'guest_store_token_{order_number}'] = token
            order.payment_reference = token
            order.save(update_fields=['payment_reference'])

            # Enregistrement Payment (traçabilité back-office/réconciliation —
            # voir audit : la boutique ne créait jusqu'ici aucune ligne
            # Payment, contrairement à la billetterie, et n'apparaissait donc
            # ni dans le back-office financier ni dans la réconciliation
            # automatique).
            from apps.payments.models import Payment
            Payment.objects.get_or_create(
                guest_product_order=order,
                defaults={
                    'amount': order.total, 'currency': 'XOF',
                    'provider': Payment.Provider.PAYDUNYA,
                    'paydunya_token': token, 'status': Payment.Status.PENDING,
                },
            )

            log_action(
                action=AuditLog.Action.PAYMENT_INITIATED,
                description=f"Paiement initié pour la commande boutique invité {order_number}",
                model_name='GuestProductOrder', object_id=order_number,
                metadata={'amount': str(order.total), 'provider': 'paydunya'},
                ip_address=get_client_ip(request),
            )
            return redirect(data['response_text'])
        else:
            log_action(
                action=AuditLog.Action.PAYMENT_FAILED,
                description=f"Échec d'initiation du paiement boutique invité {order_number}",
                model_name='GuestProductOrder', object_id=order_number,
                metadata={'reason': str(data.get('response_text', ''))[:200]},
                ip_address=get_client_ip(request),
            )
            messages.error(request, f"Erreur PayDunya : {data.get('response_text')}")

    except Exception as e:
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description=f"Erreur connexion PayDunya (boutique invité) {order_number}",
            model_name='GuestProductOrder', object_id=order_number,
            metadata={'reason': str(e)[:200]},
            ip_address=get_client_ip(request),
        )
        messages.error(request, f"Erreur connexion : {e}")

    return redirect('store:detail', slug=order.product.slug)


def guest_store_payment_return(request, order_number):
    """Retour paiement PayDunya — boutique invité."""
    from apps.payments.paydunya import PayDunyaService

    order = get_object_or_404(GuestProductOrder, order_number=order_number)

    if order.status == GuestProductOrder.Status.PAID:
        return redirect('store:guest_confirmation', order_number=order_number)

    token = (
        request.GET.get('token', '').strip()
        or request.session.get(f'guest_store_token_{order_number}', '')
        or order.payment_reference or ''
    )

    if token:
        result = PayDunyaService.verify_payment(token)
        status = result.get('status', '') or result.get('data', {}).get('invoice', {}).get('status', '')

        if result.get('success') and status == 'completed':
            # mark_as_paid() est verrouillé et idempotent : si le webhook a
            # déjà confirmé la commande entre-temps, il renvoie False et on
            # évite de dupliquer le log d'audit et l'email de confirmation.
            # ✅ H-2 : passe désormais par le helper sécurisé — une
            # ValueError (stock insuffisant) est tracée et alertée au lieu
            # de faire planter cette vue avec une 500 pour un client qui
            # vient de payer.
            newly_confirmed, stock_conflict = _confirm_guest_product_order_safely(
                order, token, result, source='retour'
            )
            if newly_confirmed:
                try:
                    from apps.notifications.service import NotificationService
                    NotificationService.guest_store_order_confirmed(order)
                except Exception as e:
                    logger.error(f"Email guest store erreur: {e}")
                messages.success(request, f"Commande {order.order_number} confirmée !")
            elif stock_conflict:
                # ✅ H-2 : le client a bien payé — on ne lui montre jamais
                # d'erreur serveur brute, mais un message clair. Le back-
                # office a déjà été alerté par _confirm_guest_product_order_safely.
                messages.warning(
                    request,
                    "Votre paiement a bien été reçu. Votre commande est en "
                    "cours de traitement et notre équipe vous contactera "
                    "sous peu concernant sa disponibilité."
                )
            else:
                messages.success(request, f"Commande {order.order_number} confirmée !")

    return redirect('store:guest_confirmation', order_number=order_number)


def guest_store_confirmation(request, order_number):
    """Page de confirmation boutique invité."""
    order = get_object_or_404(GuestProductOrder, order_number=order_number)
    download_links = GuestDownloadLink.objects.filter(order=order) if order.product.is_digital else []

    return render(request, 'store/guest_confirmation.html', {
        'order': order,
        'download_links': download_links,
    })


@csrf_exempt
@require_POST
@ratelimit(key='ip', rate='30/m', block=True)
def guest_store_webhook(request):
    """Webhook PayDunya boutique invité."""

    if not request.body:
        return HttpResponse('EMPTY', status=200)

    # 🔒 VÉRIFICATION SIGNATURE PAYDUNYA
    from apps.payments.paydunya import PayDunyaService
    if not PayDunyaService.verify_webhook_signature(request):
        logger.error("Guest store webhook rejeté : signature PayDunya invalide")
        log_action(
            action=AuditLog.Action.PAYMENT_FAILED,
            description="Webhook boutique invité rejeté : signature PayDunya invalide",
            model_name='GuestProductOrder', object_id='',
            ip_address=get_client_ip(request),
        )
        return HttpResponse('FORBIDDEN', status=403)

    try:
        data = json.loads(request.body)
        invoice_data = data.get('data', {})
        custom_data  = invoice_data.get('custom_data', {})
        status       = invoice_data.get('invoice', {}).get('status', '')
        token        = invoice_data.get('invoiceToken', '')
        order_number = custom_data.get('guest_store_order_number', '')

        # 🔒 Vérification serveur-à-serveur via l'API PayDunya
        if token and status == 'completed':
            result = PayDunyaService.verify_payment(token)
            if result.get('status') != 'completed':
                logger.warning(f"Guest store webhook: paiement non confirmé par API - {token}")
                return HttpResponse('OK', status=200)

        if status == 'completed' and order_number:
            try:
                order = GuestProductOrder.objects.get(
                    order_number=order_number,
                    status=GuestProductOrder.Status.PENDING
                )
                # mark_as_paid() est verrouillé et idempotent : si le retour
                # navigateur a déjà confirmé la commande entre-temps, il
                # renvoie False et on évite de dupliquer log/email.
                # ✅ H-2 : passe par le helper sécurisé — avant ce correctif,
                # une ValueError (stock insuffisant) ici était avalée par le
                # `except Exception` générique de cette vue, qui renvoyait
                # quand même "OK" à PayDunya (donc jamais de retry) sans que
                # personne ne soit alerté. Le conflit est maintenant tracé
                # en AuditLog et notifié aux admins par email.
                newly_confirmed, stock_conflict = _confirm_guest_product_order_safely(
                    order, token, data, source='webhook'
                )
                if newly_confirmed:
                    try:
                        from apps.notifications.service import NotificationService
                        NotificationService.guest_store_order_confirmed(order)
                    except Exception as e:
                        logger.error(f"Email guest store erreur (webhook) : {e}")
            except GuestProductOrder.DoesNotExist:
                log_action(
                    action=AuditLog.Action.PAYMENT_FAILED,
                    description=f"Webhook boutique invité : commande {order_number} introuvable ou déjà traitée",
                    model_name='GuestProductOrder', object_id=order_number,
                    ip_address=get_client_ip(request),
                )

        return HttpResponse('OK', status=200)
    except Exception as e:
        logger.error(f"Guest store webhook error: {e}")
        return HttpResponse('OK', status=200)


def guest_download_file(request, token):
    """Téléchargement sécurisé invité avec filigrane."""
    link = get_object_or_404(GuestDownloadLink, token=token)

    if link.is_expired:
        return render(request, 'store/download_expired.html', {'link': link, 'reason': 'expired'})
    if link.is_exhausted:
        return render(request, 'store/download_expired.html', {'link': link, 'reason': 'exhausted'})

    link.download_count += 1
    link.save(update_fields=['download_count'])

    product = link.product
    if not product.digital_file:
        raise Http404

    buyer_name = link.order.buyer_name
    order_number = link.order.order_number

    from .watermark import add_watermark
    watermarked, filename = add_watermark(
        product.digital_file.path, buyer_name, order_number
    )

    if watermarked:
        response = FileResponse(watermarked, as_attachment=True, filename=filename)
    else:
        response = FileResponse(
            open(product.digital_file.path, 'rb'),
            as_attachment=True,
            filename=os.path.basename(product.digital_file.path)
        )

    return response


def guest_store_payment_cancel(request, order_number):
    """
    Annulation paiement boutique invité.

    Ne marque annulé que si la commande est encore PENDING — évite
    d'écraser un statut PAID si un webhook est arrivé entre-temps (même
    principe que guest_payment_cancel côté billetterie). Redirige vers la
    page de confirmation (qui affiche un message distinct par statut)
    plutôt que vers la fiche produit, pour rester cohérent avec le parcours
    billetterie.
    """
    order = get_object_or_404(GuestProductOrder, order_number=order_number)
    if order.status == GuestProductOrder.Status.PENDING:
        from apps.payments.models import Payment

        # Ferme les deux portes de la course annulation/réconciliation :
        # la commande devient terminalement CANCELLED et son Payment PENDING
        # ne doit plus être candidat à reconcile_pending_payments.
        order.status = GuestProductOrder.Status.CANCELLED
        order.save(update_fields=['status'])
        Payment.objects.filter(
            guest_product_order=order, status=Payment.Status.PENDING,
        ).update(status=Payment.Status.CANCELLED)

        log_action(
            action=AuditLog.Action.PAYMENT_CANCELLED,
            description=(
                f"Paiement annulé par l'acheteur pour la commande boutique invité {order_number}. "
                f"Les paiements PENDING associés ont été clôturés pour empêcher toute "
                f"confirmation tardive par la réconciliation."
            ),
            model_name='Payment', object_id=order_number,
            ip_address=get_client_ip(request),
        )
    return redirect('store:guest_confirmation', order_number=order.order_number)
