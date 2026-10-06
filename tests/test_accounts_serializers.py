"""
Tests des sérialiseurs API — apps/accounts/serializers.py

Couvre :
- UserAddressSerializer : champs + read-only
- UserPublicSerializer : champs publics uniquement
- UserProfileSerializer : full_name + addresses
- RegisterSerializer : mot de passe cohérent, rôles autorisés, création user
- ChangePasswordSerializer : mot de passe cohérent
"""
from django.test import TestCase

from apps.accounts.models import CustomUser, UserAddress
from apps.accounts.serializers import (
    UserAddressSerializer,
    UserPublicSerializer,
    UserProfileSerializer,
    RegisterSerializer,
    ChangePasswordSerializer,
)


class UserAddressSerializerTests(TestCase):
    """Tests de UserAddressSerializer."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='u@test.com', password='pass',
        )

    def test_serializer_retourne_les_champs(self):
        """L'adresse sérialisée contient les champs attendus."""
        addr = UserAddress.objects.create(
            user=self.user, label='Maison',
            full_name='Ali B', phone='+2250700000000',
            address_line1='Rue 1', city='Abidjan',
            zone='Cocody', is_default=True,
        )
        data = UserAddressSerializer(addr).data

        self.assertEqual(data['label'], 'Maison')
        self.assertEqual(data['city'], 'Abidjan')
        self.assertIn('shipping_cost', data)

    def test_shipping_cost_read_only(self):
        """shipping_cost ne peut pas être modifié via l'input."""
        serializer = UserAddressSerializer()
        self.assertIn('shipping_cost', serializer.fields)
        self.assertTrue(serializer.fields['shipping_cost'].read_only)


class UserPublicSerializerTests(TestCase):
    """Tests de UserPublicSerializer."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='pub@test.com', password='pass',
            first_name='Org', last_name='Anisateur',
        )
        self.user.organization_name = 'Ma Prod'
        self.user.save()

    def test_champs_publics_uniquement(self):
        """Le sérialiseur ne doit pas exposer email ni phone."""
        data = UserPublicSerializer(self.user).data

        self.assertNotIn('email', data)
        self.assertNotIn('phone_number', data)
        self.assertIn('display_name', data)
        self.assertIn('organization_name', data)
        self.assertEqual(data['organization_name'], 'Ma Prod')

    def test_display_name_calculé(self):
        """display_name est bien exposé."""
        data = UserPublicSerializer(self.user).data
        self.assertIn('display_name', data)


class UserProfileSerializerTests(TestCase):
    """Tests de UserProfileSerializer."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='me@test.com', password='pass',
            first_name='Mon', last_name='Nom',
        )

    def test_full_name_calcule(self):
        """full_name = prénom + nom."""
        data = UserProfileSerializer(self.user).data
        self.assertEqual(data['full_name'], 'Mon Nom')

    def test_champs_sensibles_read_only(self):
        """email, role, is_organizer_verified sont read-only."""
        serializer = UserProfileSerializer()
        for field in ('id', 'email', 'role', 'is_organizer_verified', 'date_joined'):
            self.assertTrue(
                serializer.fields[field].read_only,
                f"Le champ '{field}' devrait être read-only",
            )

    def test_addresses_incluses(self):
        """Les adresses de l'utilisateur sont exposées."""
        UserAddress.objects.create(
            user=self.user, label='Bureau',
            full_name='Mon Nom', phone='+2250700000000',
            address_line1='Rue 2', city='Abidjan',
            zone='Plateau',
        )
        data = UserProfileSerializer(self.user).data
        self.assertEqual(len(data['addresses']), 1)
        self.assertEqual(data['addresses'][0]['label'], 'Bureau')


class RegisterSerializerTests(TestCase):
    """Tests de RegisterSerializer."""

    def _base_data(self, **overrides):
        data = {
            'email': 'new@test.com',
            'first_name': 'Nou',
            'last_name': 'Veau',
            'phone_number': '+2250700000000',
            'role': CustomUser.Role.ORGANIZER,
            'password': 'MotDePasse123!',
            'password_confirm': 'MotDePasse123!',
        }
        data.update(overrides)
        return data

    def test_register_valide(self):
        """Données valides → serializer.is_valid() True."""
        serializer = RegisterSerializer(data=self._base_data())
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_mots_de_passe_differents_rejete(self):
        """password != password_confirm → erreur."""
        serializer = RegisterSerializer(data=self._base_data(
            password='MotDePasse123!',
            password_confirm='AutreMotDePasse456!',
        ))
        self.assertFalse(serializer.is_valid())
        self.assertIn('password', serializer.errors)

    def test_role_non_autorise_rejete(self):
        """role=ADMIN → rejeté (seuls ORGANIZER autorisés)."""
        serializer = RegisterSerializer(data=self._base_data(
            role=CustomUser.Role.ADMIN,
        ))
        self.assertFalse(serializer.is_valid())
        self.assertIn('role', serializer.errors)

    def test_mot_de_passe_faible_rejete(self):
        """Mot de passe trop simple → rejeté par validate_password."""
        serializer = RegisterSerializer(data=self._base_data(
            password='123',
            password_confirm='123',
        ))
        self.assertFalse(serializer.is_valid())
        self.assertIn('password', serializer.errors)

    def test_creation_user_avec_mot_de_passe_hashe(self):
        """create() sauvegarde un user avec mot de passe hashé."""
        serializer = RegisterSerializer(data=self._base_data())
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        self.assertEqual(user.email, 'new@test.com')
        self.assertTrue(user.check_password('MotDePasse123!'))
        # Le password n'est PAS en clair
        self.assertNotEqual(user.password, 'MotDePasse123!')


class ChangePasswordSerializerTests(TestCase):
    """Tests de ChangePasswordSerializer."""

    def test_changement_valide(self):
        serializer = ChangePasswordSerializer(data={
            'old_password': 'AncienPass123!',
            'new_password': 'NouveauPass456!',
            'new_password_confirm': 'NouveauPass456!',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_nouveaux_mots_differents_rejete(self):
        serializer = ChangePasswordSerializer(data={
            'old_password': 'AncienPass123!',
            'new_password': 'NouveauPass456!',
            'new_password_confirm': 'Different789!',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('new_password', serializer.errors)