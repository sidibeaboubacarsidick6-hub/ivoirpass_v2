"""
IvoirPass V2 — Sérialiseurs API pour les comptes utilisateurs
"""
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import CustomUser, UserAddress


class UserAddressSerializer(serializers.ModelSerializer):
    shipping_cost = serializers.ReadOnlyField()

    class Meta:
        model = UserAddress
        fields = [
            'id', 'label', 'full_name', 'phone',
            'address_line1', 'address_line2', 'city',
            'zone', 'is_default', 'shipping_cost', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'shipping_cost']


class UserPublicSerializer(serializers.ModelSerializer):
    """
    Sérialiseur public — informations visibles par tous.
    Utilisé pour afficher le profil d'un organisateur sur un événement.
    """
    display_name = serializers.ReadOnlyField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'display_name', 'avatar',
            'organization_name', 'organization_description',
            'organization_logo', 'organization_website',
            'city', 'is_organizer_verified',
        ]


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Sérialiseur profil complet — pour l'utilisateur connecté.
    """
    display_name = serializers.ReadOnlyField()
    full_name = serializers.SerializerMethodField()
    addresses = UserAddressSerializer(many=True, read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'email', 'first_name', 'last_name',
            'full_name', 'display_name', 'phone_number',
            'role', 'avatar', 'bio', 'city',
            'preferred_language',
            'is_organizer_verified',
            'organization_name', 'organization_description',
            'organization_logo', 'organization_website',
            'notify_email', 'notify_sms', 'notify_push',
            'date_joined', 'addresses',
        ]
        read_only_fields = [
            'id', 'email', 'role',
            'is_organizer_verified', 'date_joined'
        ]

    def get_full_name(self, obj):
        return obj.get_full_name()


class RegisterSerializer(serializers.ModelSerializer):
    """
    Sérialiseur d'inscription.
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = CustomUser
        fields = [
            'email', 'first_name', 'last_name',
            'phone_number', 'role',
            'password', 'password_confirm'
        ]

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password": "Les mots de passe ne correspondent pas."
            })
        # Seuls ces rôles sont autorisés à l'inscription publique
        allowed_roles = [
            CustomUser.Role.ORGANIZER,
        ]
        if attrs.get('role', CustomUser.Role.PARTICIPANT) not in allowed_roles:
            raise serializers.ValidationError({
                "role": "Rôle non autorisé à l'inscription."
            })
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = CustomUser(**validated_data)
        user.set_password(password)
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """Sérialiseur pour le changement de mot de passe."""
    old_password = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password": "Les nouveaux mots de passe ne correspondent pas."
            })
        return attrs
