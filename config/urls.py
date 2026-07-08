"""
IvoirPass V2 — URLs principales
"""
from apps.dashboard.admin import bceao_report_view
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.accounts import views as accounts_views

admin.site.site_header = "IvoirPass V2 — Administration"
admin.site.site_title  = "IvoirPass Admin"
admin.site.index_title = "Tableau de bord administrateur"

urlpatterns = [
    path('admin/bceao-report/', bceao_report_view, name='bceao-report'),
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('redirect/', accounts_views.post_login_redirect, name='post_login'),

    # Alias global home (sans namespace)
    path('', accounts_views.home, name='home'),

    # Applications
    path('', include('apps.accounts.urls', namespace='accounts')),
    path('evenements/', include('apps.events.urls',    namespace='events')),
    path('billets/',    include('apps.tickets.urls',   namespace='tickets')),
    path('paiements/',  include('apps.payments.urls',  namespace='payments')),
    path('dashboard/',  include('apps.dashboard.urls', namespace='dashboard')),
    path('scanner/',    include('apps.scanner.urls',   namespace='scanner')),
    path('boutique/',   include('apps.store.urls',     namespace='store')),
    path('', include('apps.core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
