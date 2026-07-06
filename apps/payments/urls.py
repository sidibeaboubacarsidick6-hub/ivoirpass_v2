"""
IvoirPass V2 — URLs des paiements
"""
from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Initiation du paiement
    path(
        'payer/<str:order_number>/',
        views.initiate_payment,
        name='initiate'
    ),

    # Retour PayDunya après paiement
    path(
        'retour/<str:order_number>/',
        views.payment_return,
        name='return'
    ),

    # Annulation
    path(
        'annulation/<str:order_number>/',
        views.payment_cancel,
        name='cancel'
    ),

    # Webhook PayDunya (callback automatique)
    path(
        'webhook/',
        views.payment_webhook,
        name='webhook'
    ),

    # Vérification AJAX du statut
    path(
        'statut/<str:order_number>/',
        views.payment_status,
        name='status'
    ),
]