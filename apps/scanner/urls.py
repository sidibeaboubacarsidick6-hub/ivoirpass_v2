"""
IvoirPass V2 — URLs du Scanner
"""
from django.urls import path
from . import views

app_name = 'scanner'

urlpatterns = [
    # Accueil scanner
    path('',
         views.scanner_index, name='index'),

    # Interface de scan d'un événement
    path('evenement/<int:event_id>/',
         views.scan_event, name='scan_event'),

    # API de validation QR (appelée par le JS)
    path('valider/',
         views.validate_qr, name='validate_qr'),

    # Historique des scans
    path('evenement/<int:event_id>/historique/',
         views.scan_history, name='history'),

    # Application de scan installable (PWA) — remplace scanner_app en local
    path('app/',
         views.scanner_app, name='app'),
]