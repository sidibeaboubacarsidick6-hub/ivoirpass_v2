"""
IvoirPass V2 — URLs de la boutique culturelle
"""
from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    # ============================================
    # ROUTES FIXES POUR ACHATS SANS COMPTE (GUEST)
    # ============================================
    path('acheter/<slug:slug>/',
         views.guest_buy_product, name='guest_buy'),
    path('guest/payer/<str:order_number>/',
         views.guest_store_payment_initiate, name='guest_payment'),
    path('guest/retour/<str:order_number>/',
         views.guest_store_payment_return, name='guest_return'),
    path('guest/confirmation/<str:order_number>/',
         views.guest_store_confirmation, name='guest_confirmation'),
    path('guest/webhook/',
         views.guest_store_webhook, name='guest_webhook'),
    path('guest/telecharger/<uuid:token>/',
         views.guest_download_file, name='guest_download'),
    path('guest/annulation/<str:order_number>/',
         views.guest_store_payment_cancel, name='guest_payment_cancel'),

    # ============================================
    # ROUTES FIXES POUR UTILISATEURS AUTHENTIFIÉS
    # ============================================
    # Commandes
    path('mes-commandes/',
         views.my_orders, name='my_orders'),
    path('mes-commandes/<str:order_number>/',
         views.order_detail, name='order_detail'),

    # Gestion des produits (vendeurs)
    path('mes-produits/',
         views.my_products, name='my_products'),
    path('mes-produits/creer/',
         views.product_create, name='product_create'),
    path('mes-produits/<slug:slug>/modifier/',
         views.product_edit, name='product_edit'),
    path('mes-produits/<slug:slug>/supprimer/',
         views.product_delete, name='product_delete'),

    # ============================================
    # ROUTES DE PAIEMENT (authentifié)
    # ============================================
    path('payer/<str:order_number>/',
         views.store_payment_initiate, name='payment_initiate'),
    path('retour/<str:order_number>/',
         views.store_payment_return, name='payment_return'),
    path('annulation/<str:order_number>/',
         views.store_payment_cancel, name='payment_cancel'),
    path('paiement/statut/<str:order_number>/',
         views.store_payment_status, name='payment_status'),
    path('webhook/',
         views.store_webhook, name='webhook'),

    # ============================================
    # TÉLÉCHARGEMENT (authentifié)
    # ============================================
    path('telecharger/<uuid:token>/',
         views.download_file, name='download'),

    # ============================================
    # ROUTES DYNAMIQUES (EN DERNIER)
    # ============================================
    # Page d'accueil de la boutique
    path('',
         views.store_list, name='list'),
    
    # Détail d'un produit (slug)
    path('<slug:slug>/',
         views.store_detail, name='detail'),
    
    # Achat d'un produit (authentifié)
    path('<slug:slug>/acheter/',
         views.buy_product, name='buy'),
]