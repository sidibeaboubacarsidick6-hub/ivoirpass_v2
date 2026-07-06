"""
IvoirPass V2 — Vues de paiement PayDunya
"""
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone
from apps.tickets.models import Order
from .models import Payment
from .paydunya import PayDunyaService

logger = logging.getLogger(__name__)


@login_required
def initiate_payment(request, order_number):
    """
    Initie le paiement PayDunya pour une commande.
    Redirige l'utilisateur vers la page de paiement PayDunya.
    """
    order = get_object_or_404(
        Order,
        order_number=order_number,
        buyer=request.user,
        status=Order.Status.PENDING
    )

    # Crée l'enregistrement de paiement
    payment = Payment.objects.create(
        order    = order,
        amount   = order.total,
        currency = 'XOF',
        status   = Payment.Status.PENDING,
        provider = Payment.Provider.PAYDUNYA,
    )

    # Appel à l'API PayDunya
    result = PayDunyaService.create_invoice(order, request)

    if result['success']:
        # Sauvegarde le token PayDunya
        payment.paydunya_token = result['token']
        payment.save(update_fields=['paydunya_token'])

        # Sauvegarde le token en session pour la vérification au retour
        request.session[f'paydunya_token_{order_number}'] = result['token']

        logger.info(
            f"Redirection vers PayDunya — "
            f"Commande: {order_number}, Token: {result['token']}"
        )

        # Redirige vers PayDunya
        return redirect(result['payment_url'])

    else:
        # Échec de création de facture
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])

        messages.error(
            request,
            f"Impossible d'initier le paiement : {result['error']}"
        )
        return redirect('tickets:checkout')


def payment_return(request, order_number):
    """
    Retour après paiement PayDunya.
    Vérifie le paiement et confirme la commande.
    """
    # ✅ Récupère la commande sans exiger l'authentification
    order = get_object_or_404(Order, order_number=order_number)
    
    # ✅ Si déjà payée, redirection directe
    if order.status == Order.Status.PAID:
        messages.success(request, f"Commande {order.order_number} déjà confirmée !")
        return redirect('tickets:confirmation', order_number=order.order_number)

    # 🔥 Récupération du token
    token = request.GET.get('token', '').strip()
    if not token:
        token = request.session.get(f'paydunya_token_{order_number}', '')
    if not token:
        payment = order.payments.filter(status=Payment.Status.PENDING).first()
        if payment:
            token = payment.paydunya_token

    logger.info(f"[RETOUR BILLETS] Commande {order_number} token={token}")

    if not token:
        messages.error(request, "Token introuvable.")
        return redirect('tickets:checkout')

    # 🔥 Vérification forcée auprès de PayDunya
    result = PayDunyaService.verify_payment(token)
    status = result.get('status', '')
    
    if not status:
        status = result.get('data', {}).get('invoice', {}).get('status', '')
    if not status:
        status = result.get('data', {}).get('status', '')

    logger.info(f"[RETOUR BILLETS] Status={status}")

    # 🔥 Confirmer si status = completed OU response_code = 00
    is_completed = (
        status == 'completed' 
        or result.get('data', {}).get('response_code') == '00'
        or result.get('success') == True
    )

    if is_completed and order.status == Order.Status.PENDING:
        # ✅ Confirmer la commande
        _confirm_order(order, token, result.get('data', {}))
        
        # ✅ Remet l'utilisateur dans la session s'il s'est déconnecté
        if not request.user.is_authenticated:
            # Reconnecte l'utilisateur via la commande
            from django.contrib.auth import login
            login(request, order.buyer)
        
        messages.success(
            request,
            f"🎉 Paiement confirmé ! Commande {order.order_number} validée."
        )
        return redirect('tickets:confirmation', order_number=order.order_number)

    elif status == 'pending':
        messages.warning(request, "Paiement en cours de traitement.")
        return render(request, 'payments/pending.html', {
            'order': order,
            'token': token,
        })

    else:
        messages.error(request, "Le paiement n'a pas abouti. Veuillez réessayer.")
        return redirect('tickets:checkout')

@login_required
def payment_cancel(request, order_number):
    """
    URL appelée si l'utilisateur annule le paiement sur PayDunya.
    """
    order = get_object_or_404(
        Order,
        order_number=order_number,
        buyer=request.user
    )

    # Marque le paiement comme annulé
    order.payments.filter(
        status=Payment.Status.PENDING
    ).update(status=Payment.Status.CANCELLED)

    messages.warning(
        request,
        "Vous avez annulé le paiement. "
        "Votre panier est conservé."
    )
    return redirect('tickets:cart')


@csrf_exempt
@require_POST
def payment_webhook(request):
        # 🔥 DEBUG: Afficher TOUT ce que PayDunya envoie
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 50)
    logger.info("WEBHOOK RECU")
    logger.info(f"Content-Type: {request.content_type}")
    logger.info(f"Body brut: {request.body}")
    logger.info(f"POST dict: {request.POST}")
    logger.info("=" * 50)
    """
    Webhook PayDunya — appelé automatiquement par PayDunya
    après confirmation du paiement côté opérateur.
    """
    import urllib.parse
    
    try:
        logger.info(f"Webhook BODY: {request.body[:500]}")
        logger.info(f"Webhook POST: {request.POST}")
        logger.info(f"Webhook content_type: {request.content_type}")
        
        # 🔥 Récupération des données quel que soit le format
        raw_data = {}
        token = None
        
        if request.content_type and 'application/json' in request.content_type:
            raw_data = json.loads(request.body)
            logger.info(f"Webhook JSON: {raw_data}")
            
            # Extraction token
            token = raw_data.get('invoiceToken', '') or raw_data.get('token', '')
            
            # Extraction custom_data
            custom_data = raw_data.get('data', {}).get('custom_data', {})
            order_number = custom_data.get('order_number', '')
            
        else:
            # Form-data
            raw_data = request.POST.dict()
            logger.info(f"Webhook form-data: {raw_data}")
            
            # Extraction token
            token = raw_data.get('invoiceToken', '') or raw_data.get('token', '')
            
            # Extraction order_number depuis custom_data
            custom_data_str = raw_data.get('custom_data', '{}')
            try:
                if isinstance(custom_data_str, str):
                    custom_data = json.loads(custom_data_str)
                else:
                    custom_data = custom_data_str
                order_number = custom_data.get('order_number', '')
            except:
                order_number = ''
            
            # Si toujours pas, chercher dans data
            if not order_number and 'data' in raw_data:
                data_param = raw_data.get('data', '')
                if isinstance(data_param, str):
                    parsed = urllib.parse.parse_qs(data_param)
                    order_number = parsed.get('order_number', [''])[0]
        
        logger.info(f"Token extrait: {token}")
        logger.info(f"Order_number extrait: {order_number}")
        
        # 🔥 Si order_number manquant, on le récupère via le token
        if not order_number and token:
            logger.info(f"Order_number manquant, recherche via token: {token}")
            
            # Chercher dans Payment
            payment = Payment.objects.filter(paydunya_token=token).first()
            if payment:
                order_number = payment.order.order_number
                logger.info(f"Order_number trouvé via Payment: {order_number}")
            
            # Si pas trouvé, chercher dans Order
            if not order_number:
                order = Order.objects.filter(payment_reference=token).first()
                if order:
                    order_number = order.order_number
                    logger.info(f"Order_number trouvé via Order: {order_number}")
        
        if not order_number:
            logger.error("Webhook: order_number manquant")
            return HttpResponse('ORDER_NOT_FOUND', status=400)
        
        # Récupère la commande
        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            logger.error(f"Webhook: commande {order_number} introuvable")
            return HttpResponse('ORDER_NOT_FOUND', status=404)
        
        # Traitement selon le statut
        status = raw_data.get('status', '')
        if not status:
            status = raw_data.get('data', {}).get('invoice', {}).get('status', '')
        if not status and raw_data.get('response_code') == '00':
            status = 'completed'
        
        logger.info(f"Status: {status}")
        
        if status == 'completed' and order.status == Order.Status.PENDING:
            _confirm_order(order, token, raw_data)
            logger.info(f"Webhook: commande {order_number} confirmée")
        
        elif status == 'cancelled':
            order.payments.filter(paydunya_token=token).update(status=Payment.Status.CANCELLED)
            logger.info(f"Webhook: paiement {token} annulé")
        
        return HttpResponse('OK', status=200)
        
    except json.JSONDecodeError:
        logger.error("Webhook: JSON invalide")
        return HttpResponse('OK', status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return HttpResponse('OK', status=200)

def _confirm_order(order, token, raw_data):
    """Confirme une commande après paiement — applique la commission dynamique."""
    if order.status == Order.Status.PAID:
        return

    Payment.objects.filter(
        order=order,
        paydunya_token=token
    ).update(
        status       = Payment.Status.COMPLETED,
        raw_response = raw_data,
        completed_at = timezone.now(),
    )

    order.mark_as_paid(
        payment_method    = 'paydunya',
        payment_reference = token,
    )

    # ✅ AJOUT UNIQUEMENT — Envoyer l'email avec les billets
    try:
        from apps.tickets.utils import send_ticket_email
        send_ticket_email(order)
    except Exception:
        # Silencieux — ne jamais bloquer la confirmation
        pass

@login_required
def payment_status(request, order_number):
    """
    Vérifie manuellement le statut d'un paiement en attente.
    Appelé par polling AJAX depuis la page pending.
    """
    order = get_object_or_404(
        Order,
        order_number=order_number,
        buyer=request.user
    )

    token = request.session.get(f'paydunya_token_{order_number}')
    if not token:
        payment = order.payments.filter(
            status=Payment.Status.PENDING
        ).first()
        if payment:
            token = payment.paydunya_token

    if not token:
        from django.http import JsonResponse
        return JsonResponse({'status': 'unknown'})

    result = PayDunyaService.verify_payment(token)

    from django.http import JsonResponse
    if result['success'] and result['status'] == 'completed':
        if order.status == Order.Status.PENDING:
            _confirm_order(order, token, result.get('data', {}))
        return JsonResponse({
            'status':       'completed',
            'redirect_url': f"/billets/confirmation/{order_number}/"
        })

    return JsonResponse({'status': result.get('status', 'pending')})