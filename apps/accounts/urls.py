"""
IvoirPass V2 — URLs du compte utilisateur
"""
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Page d'accueil
    path('', views.home, name='home'),

    # Profil
    path('profil/',           views.profile,         name='profile'),
    path('profil/modifier/',  views.profile_edit,    name='profile_edit'),
    path('profil/mot-de-passe/', views.change_password, name='change_password'),

    # Adresses
    path('profil/adresses/',           views.address_list,   name='addresses'),
    path('profil/adresses/<int:pk>/supprimer/', views.address_delete, name='address_delete'),
]