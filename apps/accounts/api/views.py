"""
IvoirPass V2 — Vues API pour l'authentification et les profils
"""
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import update_session_auth_hash
from ..models import CustomUser, UserAddress
from ..serializers import (
    RegisterSerializer,
    UserProfileSerializer,
    ChangePasswordSerializer,
    UserAddressSerializer,
)


class RegisterAPIView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/
    Inscription d'un nouvel utilisateur (participant ou organisateur).
    """
    queryset = CustomUser.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'message': f'Compte créé avec succès. Bienvenue sur IvoirPass, {user.get_short_name()} !',
            'email': user.email,
            'role': user.role,
        }, status=status.HTTP_201_CREATED)


class ProfileAPIView(generics.RetrieveUpdateAPIView):
    """
    GET  /api/v1/auth/profile/  — Voir son profil
    PUT  /api/v1/auth/profile/  — Modifier son profil
    PATCH /api/v1/auth/profile/ — Modification partielle
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordAPIView(APIView):
    """
    POST /api/v1/auth/change-password/
    Changement de mot de passe pour l'utilisateur connecté.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            # Vérifie l'ancien mot de passe
            if not user.check_password(serializer.validated_data['old_password']):
                return Response(
                    {'old_password': 'Mot de passe actuel incorrect.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Change le mot de passe
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            # Met à jour la session pour ne pas déconnecter l'utilisateur
            update_session_auth_hash(request, user)
            return Response(
                {'message': 'Mot de passe modifié avec succès.'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AddressListCreateAPIView(generics.ListCreateAPIView):
    """
    GET  /api/v1/auth/addresses/ — Liste des adresses
    POST /api/v1/auth/addresses/ — Ajouter une adresse
    """
    serializer_class = UserAddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserAddress.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AddressDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/v1/auth/addresses/<id>/ — Voir une adresse
    PUT    /api/v1/auth/addresses/<id>/ — Modifier
    DELETE /api/v1/auth/addresses/<id>/ — Supprimer
    """
    serializer_class = UserAddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Un utilisateur ne peut accéder qu'à ses propres adresses
        return UserAddress.objects.filter(user=self.request.user)