"""
IvoirPass V2 — URLs principales
"""
from apps.dashboard.admin import bceao_report_view
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.accounts import views as accounts_views
from apps.dashboard.admin import bceao_report_view, export_admin_csv, export_admin_excel
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from decouple import config
from django.contrib.sitemaps.views import sitemap
from apps.core.sitemaps import EventSitemap, StaticViewSitemap


admin.site.site_header = "IvoirPass V2 — Administration"
admin.site.site_title  = "IvoirPass Admin"
admin.site.index_title = "Tableau de bord administrateur"

urlpatterns = [
    path('admin/export/csv/', export_admin_csv, name='admin_export_csv'),
    path('admin/export/excel/', export_admin_excel, name='admin_export_excel'),
    path('admin/bceao-report/', bceao_report_view, name='bceao-report'),
    path(config('ADMIN_URL', default='admin/'), admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('redirect/', accounts_views.post_login_redirect, name='post_login'),

    # Documentation API (Swagger) — réservée au staff, comme les autres
    # vues qui exposent des détails techniques de la plateforme.
    path('api/schema/', staff_member_required(SpectacularAPIView.as_view()), name='schema'),
    path('api/docs/', staff_member_required(SpectacularSwaggerView.as_view(url_name='schema')), name='swagger-ui'),

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
    path('api/accounts/', include('apps.accounts.api.urls')),
    path('api/scanner/', include('apps.scanner.api.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': {'events': EventSitemap, 'static': StaticViewSitemap}}, name='django.contrib.sitemaps.views.sitemap'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
