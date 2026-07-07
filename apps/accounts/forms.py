"""
IvoirPass V2 — Formulaires du compte utilisateur
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from allauth.account.forms import SignupForm
from .models import CustomUser, UserAddress


class IvoirPassSignupForm(SignupForm):
    """
    Formulaire d'inscription étendu pour IvoirPass.
    Ajoute prénom, nom, téléphone et rôle au formulaire allauth.
    """
    first_name = forms.CharField(
        label="Prénom",
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Votre prénom',
            'autocomplete': 'given-name',
        })
    )
    last_name = forms.CharField(
        label="Nom de famille",
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Votre nom',
            'autocomplete': 'family-name',
        })
    )
    phone_number = forms.CharField(
        label="Numéro de téléphone",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+225 07 XX XX XX XX',
            'autocomplete': 'tel',
        })
    )
    role = forms.ChoiceField(
        label="Je suis",
        choices=[
            ('participant', '🎟️  Participant — J\'achète des billets et produits culturels'),
            ('organizer',   '🎪  Organisateur — Je crée et gère des événements'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='participant',
    )

    def save(self, request):
        user = super().save(request)
        user.first_name   = self.cleaned_data['first_name']
        user.last_name    = self.cleaned_data['last_name']
        user.phone_number = self.cleaned_data.get('phone_number', '')
        user.role         = self.cleaned_data['role']
        user.save()
        return user


class ProfileEditForm(forms.ModelForm):
    """Formulaire de modification du profil utilisateur."""

    class Meta:
        model = CustomUser
        fields = [
            'first_name', 'last_name', 'phone_number',
            'city', 'bio', 'avatar',
            'preferred_language',
            'notify_email', 'notify_sms', 'notify_push',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Votre prénom',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Votre nom',
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+225 07 XX XX XX XX',
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Abidjan',
            }),
            'bio': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Décrivez-vous en quelques mots...',
            }),
            'avatar': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'preferred_language': forms.Select(attrs={
                'class': 'form-select',
            }),
        }
        labels = {
            'first_name':         'Prénom',
            'last_name':          'Nom de famille',
            'phone_number':       'Téléphone',
            'city':               'Ville',
            'bio':                'Biographie',
            'avatar':             'Photo de profil',
            'preferred_language': 'Langue préférée',
            'notify_email':       'Recevoir les notifications par email',
            'notify_sms':         'Recevoir les notifications par SMS',
            'notify_push':        'Recevoir les notifications push',
        }


class OrganizerProfileForm(forms.ModelForm):
    """Formulaire supplémentaire pour les organisateurs."""

    class Meta:
        model = CustomUser
        fields = [
            'organization_name', 'organization_description',
            'organization_logo', 'organization_website',
            'kyc_identity_doc', 'kyc_proof_of_address', 'kyc_business_doc',
        ]
        widgets = {
            'organization_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de votre structure ou entreprise',
            }),
            'organization_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Décrivez votre organisation...',
            }),
            'organization_logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'organization_website': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://votre-site.com',
            }),
        }
        labels = {
            'organization_name':        'Nom de l\'organisation',
            'organization_description': 'Description',
            'organization_logo':        'Logo',
            'organization_website':     'Site web',
        }


class UserAddressForm(forms.ModelForm):
    """Formulaire d'adresse de livraison."""

    class Meta:
        model = UserAddress
        fields = [
            'label', 'full_name', 'phone',
            'address_line1', 'address_line2',
            'city', 'zone', 'is_default',
        ]
        widgets = {
            'label': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Domicile, Bureau...',
            }),
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom complet du destinataire',
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+225 07 XX XX XX XX',
            }),
            'address_line1': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Quartier, rue, numéro...',
            }),
            'address_line2': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Complément (optionnel)',
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Abidjan',
            }),
            'zone': forms.Select(attrs={'class': 'form-select'}),
        }