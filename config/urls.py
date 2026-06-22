"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
"""
IvoirPass V2 - URLs principales
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Personnalisation de l'admin Django
admin.site.site_header = "IvoirPass V2 — Administration"
admin.site.site_title = "IvoirPass Admin"
admin.site.index_title = "Tableau de bord administrateur"

urlpatterns = [
    # Administration Django
    path('admin/', admin.site.urls),

    # Authentification (allauth)
    path('accounts/', include('allauth.urls')),

    # ============================================
    # URLS DES APPLICATIONS IVOIRPASS
    # ============================================
    path('', include('apps.accounts.urls', namespace='accounts')),
    path('events/', include('apps.events.urls', namespace='events')),
    path('tickets/', include('apps.tickets.urls', namespace='tickets')),
    path('payments/', include('apps.payments.urls', namespace='payments')),
    path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),
    path('scanner/', include('apps.scanner.urls', namespace='scanner')),
    path('store/', include('apps.store.urls', namespace='store')),

    # ============================================
    # API REST FRAMEWORK
    # ============================================
    path('api/v1/auth/', include('apps.accounts.api.urls')),
    path('api/v1/events/', include('apps.events.api.urls')),
    path('api/v1/tickets/', include('apps.tickets.api.urls')),
    path('api/v1/payments/', include('apps.payments.api.urls')),
    path('api/v1/store/', include('apps.store.api.urls')),
]

# Servir les fichiers médias en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)