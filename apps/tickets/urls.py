from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    # Panier (utilisateurs connectés)
    path('panier/',
         views.cart_view,           name='cart'),
    path('panier/ajouter/<int:ticket_type_id>/',
         views.add_to_cart,         name='add_to_cart'),
    path('panier/retirer/<int:ticket_type_id>/',
         views.remove_from_cart,    name='remove_from_cart'),
    path('commander/',
         views.checkout,            name='checkout'),
    path('confirmation/<str:order_number>/',
         views.order_confirmation,  name='confirmation'),
    path('mes-billets/',
         views.my_tickets,          name='my_tickets'),
    path('mes-billets/<str:ticket_number>/',
         views.ticket_detail,       name='ticket_detail'),
    path('mes-billets/<str:ticket_number>/pdf/',
         views.download_ticket_pdf, name='download_pdf'),

    # ✅ ACHAT SANS COMPTE (GUEST)
    path('acheter/<slug:slug>/',
         views.guest_checkout,          name='guest_checkout'),
    path('guest/payer/<str:order_number>/',
         views.guest_payment_initiate,  name='guest_payment'),
    path('guest/retour/<str:order_number>/',
         views.guest_payment_return,    name='guest_return'),
    path('guest/annulation/<str:order_number>/',
         views.guest_confirmation,      name='guest_cancel'),
    path('guest/webhook/',
         views.guest_webhook,           name='guest_webhook'),
    path('guest/confirmation/<str:order_number>/',
         views.guest_confirmation,      name='guest_confirmation'),
     # Téléchargement PDF billet invité (sans compte)
    path('guest/billet/<str:ticket_number>/pdf/',
     views.download_guest_ticket_pdf,
     name='guest_download_pdf'),
]