from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('',
         views.dashboard_index,  name='index'),
    path('evenement/<slug:slug>/stats/',
         views.event_stats,      name='event_stats'),
    path('evenement/<slug:slug>/participants/',
         views.participants,     name='participants'),
    path('wallet/',
         views.wallet_view,      name='wallet'),
    path('wallet/reverser/',
         views.withdraw_request, name='withdraw'),
    path('evenement/<slug:slug>/export/',
         views.export_participants_csv, name='export_participants'),
    path('commandes-physiques/',
         views.physical_orders,  # ✅ Nom correct
         name='physical_orders'),
    path('commandes-physiques/<str:order_type>/<int:order_id>/shipped/',
         views.mark_order_shipped, name='mark_shipped'),
    path('reversement/valider/<str:reference>/',
         views.verify_otp, name='verify_otp'),
    path('audit/',
         views.audit_log, name='audit_log'),
]