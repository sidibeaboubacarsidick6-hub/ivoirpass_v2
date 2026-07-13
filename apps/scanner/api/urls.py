from django.urls import path
from . import views

app_name = 'scanner_api'

urlpatterns = [
    path('scan/', views.scan_qr_api, name='scan_qr'),
    path('check-event/', views.check_event_exists, name='check_event'),
]