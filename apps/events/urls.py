from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    # ✅ Routes fixes EN PREMIER
    path('mes-evenements/',        views.my_events,    name='my_events'),
    path('creer/',                 views.event_create, name='create'),
    path('<slug:slug>/modifier/',  views.event_edit,   name='edit'),
    path('<slug:slug>/supprimer/', views.event_delete, name='delete'),

    # ✅ Routes dynamiques EN DERNIER
    path('',                       views.event_list,   name='list'),
    path('<slug:slug>/',           views.event_detail, name='detail'),
]