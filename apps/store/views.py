"""
IvoirPass V2 — Vues de la boutique culturelle
"""
from django_ratelimit.decorators import ratelimit
import os
import json
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Product, ProductCategory, ProductOrder, DownloadLink
from .models import GuestProductOrder, GuestDownloadLink
from .forms import ProductForm

logger = logging.getLogger(__name__)


# ============================================
# VUES PUBLIQUES
# ============================================

def store_list(request):
    """Boutique publique — liste de tous les produits."""
    products = Product.objects.filter(
        status=Product.Status.PUBLISHED
    ).select_related('category', 'seller')

    # Recherche
    query = request.GET.get('q', '')
    if query:
        products = products.filter(
            Q(name__icontains=query)         |
            Q(author__icontains=query)       |
            Q(description__icontains=query)  |
            Q(tags__icontains=query)
        )

    # Filtres
    category_slug = request.GET.get('category', '')
    if category_slug:
        products = products.filter(category__slug=category_slug)

    product_type = request.GET.get('type', '')
    if product_type:
        products = products.filter(product_type=product_type)

    # Tri
    sort = request.GET.get('sort', '-created_at')
    if sort in ['-created_at', 'price', '-price', '-sold_count']:
        products = products.order_by(sort)

    # Pagination
    paginator   = Paginator(products, 12)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)

    categories = ProductCategory.objects.filter(is_active=True)

    return render(request, 'store/list.html', {
        'page_obj':     page_obj,
        'categories':   categories,
        'query':        query,
        'category_slug': category_slug,
        'product_type': product_type,
        'sort':         sort,
        'total':        paginator.count,
        'product_types': Product.ProductType.choices,
    })


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
def buy_product(request, slug):
    product = get_object_or_404(
        Product,
        slug=slug,
        status=Product.Status.PUBLISHED
    )

    if not product.is_available:
        messages.error(request, "Ce produit n'est plus disponible.")
        return redirect('store:detail', slug=slug)

    if request.method == 'POST':
        quantity        = int(request.POST.get('quantity', 1))
        delivery_method = request.POST.get(
            'delivery_method',
            'download' if product.is_digital else 'delivery'
        )
        address_id = request.POST.get('address_id')

        # Validation adresse obligatoire pour produit physique
        if product.is_physical and delivery_method == 'delivery':
            if not address_id and not request.POST.get('delivery_address', '').strip():
                messages.error(
                    request,
                    "Veuillez sélectionner ou saisir une adresse de livraison."
                )
                addresses = request.user.addresses.all()
                return render(request, 'store/checkout.html', {
                    'product':   product,
                    'addresses': addresses,
                })

        # Commission dynamique depuis le produit
        commission_rate = float(product.commission_rate) / 100
        unit_price  = product.price
        subtotal    = unit_price * quantity
        commission  = int(float(subtotal) * commission_rate)
        # Prix payé par l'acheteur = prix sans commission
        # (commission prélevée sur le vendeur au reversement)
        total = subtotal

        order = ProductOrder.objects.create(
            buyer           = request.user,
            product         = product,
            quantity        = quantity,
            unit_price      = unit_price,
            subtotal        = subtotal,
            commission      = commission,
            total           = total,
            delivery_method = delivery_method,
            status          = ProductOrder.Status.PENDING,
        )

        # ============================================
        # Sauvegarde adresse de livraison si produit physique
        # ============================================
        if delivery_method == 'delivery':
            if address_id:
                from apps.accounts.models import UserAddress
                try:
                    addr = UserAddress.objects.get(
                        pk=address_id,
                        user=request.user
                    )
                    order.delivery_name    = getattr(addr, 'full_name', '') or request.user.get_full_name()
                    order.delivery_phone   = getattr(addr, 'phone', '')
                    order.delivery_address = getattr(addr, 'address', '') or str(addr)
                    order.delivery_city    = getattr(addr, 'city', '')
                    order.delivery_commune = getattr(addr, 'commune', '')
                    order.delivery_country = getattr(addr, 'country', "Côte d'Ivoire")
                except UserAddress.DoesNotExist:
                    messages.error(request, "Adresse introuvable.")
                    addresses = request.user.addresses.all()
                    return render(request, 'store/checkout.html', {
                        'product':   product,
                        'addresses': addresses,
                    })
            else:
                order.delivery_name    = request.POST.get('delivery_name', '').strip()
                order.delivery_phone   = request.POST.get('delivery_phone', '').strip()
                order.delivery_address = request.POST.get('delivery_address', '').strip()
                order.delivery_city    = request.POST.get('delivery_city', '').strip()
                order.delivery_commune = request.POST.get('delivery_commune', '').strip()
                order.delivery_country = request.POST.get('delivery_country', "Côte d'Ivoire").strip()

            order.delivery_instructions = request.POST.get('delivery_instructions', '').strip()
            order.save(update_fields=[
                'delivery_name', 'delivery_phone', 'delivery_address',
                'delivery_city', 'delivery_commune', 'delivery_country',
                'delivery_instructions',
            ])

        return redirect(
            'store:payment_initiate',
            order_number=order.order_number
        )

    # GET — page checkout
    addresses = request.user.addresses.all() if product.is_physical else []
    return render(request, 'store/checkout.html', {
        'product':   product,
        'addresses': addresses,
    })


@login_required
def store_payment_initiate(request, order_number):
    """Initie le paiement PayDunya pour une commande boutique."""
    order = get_object_or_404(
        ProductOrder,
        order_number=order_number,
        buyer=request.user,
        status=ProductOrder.Status.PENDING
    )

    from django.conf import settings
    import requests as req

    base_url    = settings.PAYDUNYA_BASE_URL
    return_url  = f"{base_url}/boutique/retour/{order.order_number}/"
    cancel_url  = f"{base_url}/boutique/annulation/{order.order_number}/"
    webhook_url = f"{base_url}/boutique/webhook/"

    payload = {
        "store": {
            "name":        "IvoirPass Boutique",
            "tagline":     "Culture ivoirienne",
            "website_url": base_url,
        },
        "invoice": {
            "items": {
                "item_1": {
                    "name":        order.product.name,
                    "quantity":    order.quantity,
                    "unit_price":  str(order.unit_price),
                    "total_price": str(order.subtotal),
                    "description": order.product.get_product_type_display(),
                }
            },
            "total_amount": str(int(order.total)),
            "description":  f"Commande boutique {order.order_number}",
        },
        "actions": {
            "cancel_url":   cancel_url,
            "return_url":   return_url,
            "callback_url": webhook_url,
        },
        "custom_data": {
            "store_order_number": order.order_number,
            "order_uuid":         str(order.uuid),
            "buyer_email":        order.buyer.email,
        }
    }

    headers = {
        'Content-Type':         'application/json',
        'PAYDUNYA-MASTER-KEY':  settings.PAYDUNYA_MASTER_KEY,
        'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
        'PAYDUNYA-TOKEN':       settings.PAYDUNYA_TOKEN,
    }

    try:
        response = req.post(
            settings.PAYDUNYA_API_BASE + '/checkout-invoice/create',
            json=payload,
            headers=headers,
            timeout=30
        )
        data = response.json()

        if data.get('response_code') == '00':
            token = data['token']

            # ✅ On sauvegarde uniquement le token en session
            request.session[
                f'store_paydunya_token_{order.order_number}'
            ] = token

            # Sauvegarde aussi le token sur la commande pour le webhook
            order.payment_reference = token
            order.save(update_fields=['payment_reference'])

            return redirect(data['response_text'])

        else:
            messages.error(
                request,
                f"Erreur PayDunya : {data.get('response_text', 'Inconnue')}"
            )

    except Exception as e:
        messages.error(request, f"Erreur connexion PayDunya : {e}")

    return redirect('store:detail', slug=order.product.slug)


@login_required
def store_payment_status(request, order_number):
    """Vérifie le statut du paiement (AJAX)."""
    from apps.payments.paydunya import PayDunyaService
    
    order = get_object_or_404(
        ProductOrder,
        order_number=order_number,
        buyer=request.user
    )
    
    # Si déjà payé
    if order.status == ProductOrder.Status.PAID:
        return JsonResponse({
            'status': 'completed',
            'redirect_url': f"/boutique/mes-commandes/{order_number}/"
        })
    
    # Récupérer le token
    token = order.payment_reference or request.session.get(f'store_paydunya_token_{order_number}', '')
    
    if not token:
        # Chercher dans les paiements
        from apps.payments.models import Payment
        payment = Payment.objects.filter(order__order_number=order_number).first()
        if payment:
            token = payment.paydunya_token or ''
    
    if not token:
        return JsonResponse({'status': 'unknown'})
    
    # Vérifier le statut
    result = PayDunyaService.verify_payment(token)
    status = result.get('status', '') or result.get('data', {}).get('invoice', {}).get('status', '')
    
    logger.info(f"[STATUS] Commande {order_number} - statut: {status}")
    
    if status == 'completed':
        # Marquer comme payé
        order.status = ProductOrder.Status.PAID
        order.payment_method = 'paydunya'
        order.payment_reference = token
        order.paid_at = timezone.now()
        order.save()
        
        try:
            order._credit_seller_wallet()
        except Exception as e:
            logger.error(f"[STATUS] Wallet error: {e}")
        
        if order.product.is_digital:
            from .models import DownloadLink
            if not DownloadLink.objects.filter(order=order).exists():
                order._generate_download_links()
                logger.info(f"[STATUS] Liens générés")
                # ✅ Envoyer l'email avec les liens
                try:
                    from .utils import send_download_link_email
                    send_download_link_email(order)
                except Exception as e:
                    logger.error(f"[STATUS] Erreur envoi email: {e}")
        
        if order.product.is_physical:
            order.product.stock -= order.quantity
            order.product.sold_count += order.quantity
            order.product.save(update_fields=['stock', 'sold_count'])
        
        # Nettoyer la session
        if f'store_paydunya_token_{order_number}' in request.session:
            del request.session[f'store_paydunya_token_{order_number}']
        
        return JsonResponse({
            'status': 'completed',
            'redirect_url': f"/boutique/mes-commandes/{order_number}/"
        })
    
    return JsonResponse({'status': status})


@login_required
def store_payment_return(request, order_number):
    """Retour après paiement PayDunya boutique."""
    from apps.payments.paydunya import PayDunyaService

    order = get_object_or_404(
        ProductOrder,
        order_number=order_number,
        buyer=request.user
    )

    if order.status == ProductOrder.Status.PAID:
        messages.success(request, f"Commande {order.order_number} confirmée !")
        return redirect('store:order_detail', order_number=order.order_number)

    token = request.GET.get('token', '').strip()
    if not token:
        token = request.session.get(f'store_paydunya_token_{order_number}', '')
    if not token:
        token = order.payment_reference or ''
    if not token:
        from apps.payments.models import Payment
        payment = Payment.objects.filter(order__order_number=order_number).first()
        if payment:
            token = payment.paydunya_token or ''

    logger.info(f"[RETOUR] Commande {order_number} token={token}")

    if not token:
        messages.error(request, "Token introuvable.")
        return redirect('store:my_orders')

    result = PayDunyaService.verify_payment(token)
    
    status = result.get('status', '')
    if not status:
        status = result.get('data', {}).get('invoice', {}).get('status', '')
    if not status:
        status = result.get('data', {}).get('status', '')

    logger.info(f"[RETOUR] Status={status}")

    is_completed = (
        result.get('success') and status == 'completed'
    ) or (
        result.get('data', {}).get('response_code') == '00'
        and status == 'completed'
    )

    if is_completed:
        order.status = ProductOrder.Status.PAID
        order.payment_method = 'paydunya'
        order.payment_reference = token
        order.paid_at = timezone.now()
        order.save()
        
        try:
            order._credit_seller_wallet()
        except Exception as e:
            logger.error(f"[RETOUR] Wallet error: {e}")
        
        if order.product.is_digital:
            from .models import DownloadLink
            if not DownloadLink.objects.filter(order=order).exists():
                order._generate_download_links()
                logger.info(f"[RETOUR] Liens générés")
                try:
                    from .utils import send_download_link_email
                    send_download_link_email(order)
                except Exception as e:
                    logger.error(f"[RETOUR] Erreur envoi email: {e}")
        
        if order.product.is_physical:
            order.product.stock -= order.quantity
            order.product.sold_count += order.quantity
            order.product.save(update_fields=['stock', 'sold_count'])
        
        if f'store_paydunya_token_{order_number}' in request.session:
            del request.session[f'store_paydunya_token_{order_number}']
        
        messages.success(request, f"Commande {order.order_number} confirmée !")
        return redirect('store:order_detail', order_number=order.order_number)

    if status in ['pending', 'processing']:
        messages.info(request, "Paiement en cours de traitement.")
        return render(request, 'store/payment_pending.html', {
            'order': order,
            'token': token,
        })

    logger.warning(f"[RETOUR] Status non completed: {status}")
    messages.warning(request, "Paiement en cours de vérification.")
    return redirect('store:my_orders')


@login_required
def store_payment_cancel(request, order_number):
    """Annulation paiement boutique."""
    order = get_object_or_404(
        ProductOrder,
        order_number=order_number,
        buyer=request.user
    )
    order.status = ProductOrder.Status.CANCELLED
    order.save(update_fields=['status'])
    messages.warning(request, "Commande annulée.")
    return redirect('store:detail', slug=order.product.slug)


@login_required
def my_orders(request):
    """Liste des commandes de l'acheteur."""
    orders = ProductOrder.objects.filter(
        buyer=request.user
    ).select_related('product').order_by('-created_at')

    return render(request, 'store/my_orders.html', {
        'orders': orders,
    })


@login_required
def order_detail(request, order_number):
    """Détail d'une commande boutique."""
    order = get_object_or_404(
        ProductOrder,
        order_number=order_number,
        buyer=request.user
    )
    download_links = order.download_links.all()

    return render(request, 'store/order_detail.html', {
        'order':          order,
        'download_links': download_links,
    })


@login_required
def download_file(request, token):
    """
    Téléchargement sécurisé d'un fichier numérique.
    Vérifie le token, l'expiration et le nombre de téléchargements.
    """
    link = get_object_or_404(DownloadLink, token=token)

    # Vérifie que c'est bien l'acheteur
    if link.order.buyer != request.user:
        raise Http404

    # Vérifie la validité du lien
    if link.is_expired:
        messages.error(
            request,
            "Ce lien de téléchargement a expiré."
        )
        return redirect('store:order_detail',
                        order_number=link.order.order_number)

    if link.is_exhausted:
        messages.error(
            request,
            f"Limite de téléchargements atteinte "
            f"({link.max_downloads} max)."
        )
        return redirect('store:order_detail',
                        order_number=link.order.order_number)

    # Incrémente le compteur
    link.download_count += 1
    link.save(update_fields=['download_count'])

    # Sert le fichier
    product = link.product
    if not product.digital_file:
        raise Http404

    file_path = product.digital_file.path
    filename  = os.path.basename(file_path)

    response = FileResponse(
        open(file_path, 'rb'),
        as_attachment=True,
        filename=filename
    )
    return response


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
    
    if not request.body:
        logger.warning("Store webhook: body vide")
        return HttpResponse('OK', status=200)
    
    try:
        # PayDunya peut envoyer soit directement le JSON, soit dans data
        raw_data = json.loads(request.body)
        logger.info(f"Store webhook raw data: {raw_data}")
        
        # PayDunya V2 format: {"data": {"invoice": {...}, "custom_data": {...}}}
        # ou format direct: {"invoice": {...}, "custom_data": {...}}
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
        
        if status == 'completed' and order_number:
            try:
                order = ProductOrder.objects.get(
                    order_number=order_number,
                    status=ProductOrder.Status.PENDING
                )
                
                # Mise à jour manuelle de la commande
                order.status = ProductOrder.Status.PAID
                order.payment_method = 'paydunya'
                order.payment_reference = token
                order.paid_at = timezone.now()
                order.save()
                
                logger.info(f"Store webhook: commande {order_number} validée")
                
                # Crédit du vendeur
                try:
                    order._credit_seller_wallet()
                except Exception as e:
                    logger.error(f"Store webhook: erreur wallet: {e}")
                
                # Génération des liens de téléchargement si digital
                if order.product.is_digital:
                    from .models import DownloadLink
                    if not DownloadLink.objects.filter(order=order).exists():
                        order._generate_download_links()
                        # ✅ Envoyer l'email avec les liens
                        try:
                            from .utils import send_download_link_email
                            send_download_link_email(order)
                        except Exception as e:
                            logger.error(f"Store webhook: erreur envoi email: {e}")
                
                # Mise à jour du stock si physique
                if order.product.is_physical:
                    order.product.stock -= order.quantity
                    order.product.sold_count += order.quantity
                    order.product.save(update_fields=['stock', 'sold_count'])
                
            except ProductOrder.DoesNotExist:
                logger.warning(f"Store webhook: commande {order_number} introuvable ou déjà payée")
            except Exception as e:
                logger.error(f"Store webhook: erreur mise à jour: {e}")
        
        return HttpResponse('OK', status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"Store webhook: JSON invalide - {e}, body: {request.body[:200]}")
        return HttpResponse('OK', status=200)  # Toujours 200 pour PayDunya
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

        # Adresse obligatoire si livraison physique
        if delivery_method == 'delivery':
            delivery_name    = request.POST.get('delivery_name', '').strip()
            delivery_phone   = request.POST.get('delivery_phone', '').strip()
            delivery_address = request.POST.get('delivery_address', '').strip()
            delivery_city    = request.POST.get('delivery_city', '').strip()
            if not delivery_name:    errors.append("Le nom du destinataire est requis.")
            if not delivery_phone:   errors.append("Le téléphone de livraison est requis.")
            if not delivery_address: errors.append("L'adresse est requise.")
            if not delivery_city:    errors.append("La ville est requise.")

        if product.is_physical and quantity > product.stock:
            errors.append("Quantité demandée supérieure au stock disponible.")

        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'store/guest_checkout.html', {'product': product})

        # Calcul montants
        unit_price = product.price
        subtotal   = unit_price * quantity
        total      = subtotal  # Commission prélevée sur le vendeur, pas sur l'acheteur

        order = GuestProductOrder.objects.create(
            first_name = first_name,
            last_name  = last_name,
            email      = email,
            phone      = phone,
            product    = product,
            quantity   = quantity,
            unit_price = unit_price,
            subtotal   = subtotal,
            total      = total,
            delivery_method = delivery_method,
            status = GuestProductOrder.Status.PENDING,
        )

        if delivery_method == 'delivery':
            order.delivery_name         = request.POST.get('delivery_name', '').strip()
            order.delivery_phone        = request.POST.get('delivery_phone', '').strip()
            order.delivery_address      = request.POST.get('delivery_address', '').strip()
            order.delivery_city         = request.POST.get('delivery_city', '').strip()
            order.delivery_commune      = request.POST.get('delivery_commune', '').strip()
            order.delivery_country      = request.POST.get('delivery_country', "Côte d'Ivoire").strip()
            order.delivery_instructions = request.POST.get('delivery_instructions', '').strip()
            order.save()

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
            return redirect(data['response_text'])
        else:
            messages.error(request, f"Erreur PayDunya : {data.get('response_text')}")

    except Exception as e:
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
            order.mark_as_paid(payment_method='paydunya', payment_reference=token)

            try:
                from apps.notifications.service import NotificationService
                NotificationService.guest_store_order_confirmed(order)
            except Exception as e:
                logger.error(f"Email guest store erreur: {e}")

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

    try:
        data = json.loads(request.body)
        invoice_data = data.get('data', {})
        custom_data  = invoice_data.get('custom_data', {})
        status       = invoice_data.get('invoice', {}).get('status', '')
        token        = invoice_data.get('invoiceToken', '')
        order_number = custom_data.get('guest_store_order_number', '')

        if status == 'completed' and order_number:
            try:
                order = GuestProductOrder.objects.get(
                    order_number=order_number,
                    status=GuestProductOrder.Status.PENDING
                )
                order.mark_as_paid(payment_method='paydunya', payment_reference=token)
                from apps.notifications.service import NotificationService
                NotificationService.guest_store_order_confirmed(order)
            except GuestProductOrder.DoesNotExist:
                pass

        return HttpResponse('OK', status=200)
    except Exception as e:
        logger.error(f"Guest store webhook error: {e}")
        return HttpResponse('OK', status=200)


def guest_download_file(request, token):
    """
    Téléchargement sécurisé — accessible sans compte via le token unique.
    Chaque commande a ses propres liens indépendants des autres achats.
    """
    import os

    link = get_object_or_404(GuestDownloadLink, token=token)

    if link.is_expired:
        return render(request, 'store/download_expired.html', {
            'link': link, 
            'reason': 'expired'
        })

    if link.is_exhausted:
        return render(request, 'store/download_expired.html', {
            'link': link, 
            'reason': 'exhausted'
        })

    link.download_count += 1
    link.save(update_fields=['download_count'])

    product = link.product
    if not product.digital_file:
        raise Http404

    file_path = product.digital_file.path
    filename  = os.path.basename(file_path)

    response = FileResponse(
        open(file_path, 'rb'), 
        as_attachment=True, 
        filename=filename
    )
    return response


def guest_store_payment_cancel(request, order_number):
    """Annulation paiement boutique invité."""
    order = get_object_or_404(GuestProductOrder, order_number=order_number)
    order.status = GuestProductOrder.Status.CANCELLED
    order.save(update_fields=['status'])
    messages.warning(request, "Commande annulée.")
    return redirect('store:detail', slug=order.product.slug)