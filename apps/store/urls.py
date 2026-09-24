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
    # ✅ H-3 : 'my_orders' et 'download' sont conservées en simples
    # redirections (voir apps/store/views.py) — encore référencées par
    # templates/dashboard/base_dashboard.html, templates/store/detail.html
    # et templates/pages/my_orders_history.html. Les autres routes du
    # tunnel "avec compte" (achat, paiement, détail commande) ont été
    # supprimées avec leurs vues et leurs templates.
    path('mes-commandes/',
         views.my_orders, name='my_orders'),

    # Gestion des produits (vendeurs)
    path('mes-produits/',
         views.my_products, name='my_products'),
    path('mes-produits/creer/',
         views.product_create, name='product_create'),
    path('mes-produits/<slug:slug>/modifier/',
         views.product_edit, name='product_edit'),
    path('mes-produits/<slug:slug>/stats/',
         views.product_stats, name='product_stats'),
    path('mes-produits/<slug:slug>/acheteurs/',
         views.product_buyers, name='product_buyers'),
    path('mes-produits/<slug:slug>/acheteurs/export/',
         views.export_product_buyers_csv, name='export_product_buyers'),
    path('mes-produits/<slug:slug>/supprimer/',
         views.product_delete, name='product_delete'),

    # ============================================
    # TÉLÉCHARGEMENT (authentifié)
    # ============================================
    path('telecharger/<uuid:token>/',
         views.download_file, name='download'),

    # Webhook PayDunya pour les commandes "avec compte" — actif (signature
    # PayDunya vérifiée), conservé même si le tunnel d'achat correspondant
    # a été retiré : nécessaire pour tout paiement encore en cours côté
    # PayDunya sur une ProductOrder existante.
    path('webhook/',
         views.store_webhook, name='webhook'),

    # ============================================
    # ROUTES DYNAMIQUES (EN DERNIER)
    # ============================================
    # Page d'accueil de la boutique
    path('',
         views.store_list, name='list'),
    
    # Détail d'un produit (slug)
    path('<slug:slug>/',
         views.store_detail, name='detail'),
]