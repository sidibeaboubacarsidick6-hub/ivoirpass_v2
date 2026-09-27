from django.urls import path
from . import views

app_name = 'scanner_api'

urlpatterns = [
    path('scan/', views.scan_qr_api, name='scan_qr'),
    path('check-event/', views.check_event_exists, name='check_event'),

    # ── Chantier B — Scanner offline ─────────────────────────────────
    path(
        'prepare/<int:event_id>/',
        views.prepare_event_offline, name='prepare_offline',
    ),
    path(
        'sync/',
        views.sync_offline_scans, name='sync_offline',
    ),
]