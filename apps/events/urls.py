from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    # ✅ Routes fixes EN PREMIER
    path('mes-evenements/',        views.my_events,    name='my_events'),
    path('creer/',                 views.event_create, name='create'),
    path('<slug:slug>/modifier/',  views.event_edit,   name='edit'),
    path('<slug:slug>/supprimer/', views.event_delete, name='delete'),
    path('<slug:slug>/agents-scanner/', views.assign_scanner_agents, name='assign_scanner_agents'),
    path('agents-scanner/nouveau/', views.create_scanner_agent, name='create_scanner_agent'),

    # 🎫 Codes de billets gratuits (Vague 2.2)
    path('<slug:slug>/code-gratuit/',            views.claim_free_ticket,           name='claim_free_ticket'),
    path('<slug:slug>/codes-gratuits/',          views.free_tickets_list,           name='free_tickets_list'),
    path('<slug:slug>/codes-gratuits/generer/',  views.generate_free_tickets,       name='generate_free_tickets'),
    path('<slug:slug>/codes-gratuits/export.csv', views.download_free_tickets_csv,   name='download_free_tickets_csv'),

    # ✅ Routes dynamiques EN DERNIER
    path('',                       views.event_list,   name='list'),
    path('<slug:slug>/',           views.event_detail, name='detail'),
]