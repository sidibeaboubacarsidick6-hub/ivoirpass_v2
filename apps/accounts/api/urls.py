"""
IvoirPass V2 — URLs de l'API Authentification
"""
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from . import views

urlpatterns = [
    # JWT Authentication
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # Inscription & Profil
    path('register/', views.RegisterAPIView.as_view(), name='api_register'),
    path('profile/', views.ProfileAPIView.as_view(), name='api_profile'),
    path('change-password/', views.ChangePasswordAPIView.as_view(), name='api_change_password'),
    path('addresses/', views.AddressListCreateAPIView.as_view(), name='api_addresses'),
    path('addresses/<int:pk>/', views.AddressDetailAPIView.as_view(), name='api_address_detail'),
]