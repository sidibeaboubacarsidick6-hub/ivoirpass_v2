from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    # ✅ H-3 : ces 3 routes ne sont conservées (en simples redirections vers
    # 'home', voir apps/tickets/views.py) que parce que apps/payments/views.py
    # les référence encore (ancien flux de paiement "avec compte").
    path('panier/',
         views.cart_view,           name='cart'),
    path('commander/',
         views.checkout,            name='checkout'),
    path('confirmation/<str:order_number>/',
         views.order_confirmation,  name='confirmation'),

    # ✅ ACHAT SANS COMPTE (GUEST)
    path('acheter/<slug:slug>/',
         views.guest_checkout,          name='guest_checkout'),
    path('guest/payer/<str:order_number>/',
         views.guest_payment_initiate,  name='guest_payment'),
    path('guest/retour/<str:order_number>/',
         views.guest_payment_return,    name='guest_return'),
    path('guest/annulation/<str:order_number>/',
         views.guest_payment_cancel,    name='guest_cancel'),
    path('guest/webhook/',
         views.guest_webhook,           name='guest_webhook'),
    path('guest/confirmation/<str:order_number>/',
         views.guest_confirmation,      name='guest_confirmation'),
     # Téléchargement PDF billet invité (sans compte)
    path('guest/billet/<str:ticket_number>/pdf/',
     views.download_guest_ticket_pdf,
     name='guest_download_pdf'),
]