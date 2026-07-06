"""
IvoirPass V2 — Formulaires de la boutique
"""
from django import forms
from .models import Product, ProductCategory


class ProductForm(forms.ModelForm):
    """Formulaire de création/modification d'un produit."""

    class Meta:
        model  = Product
        fields = [
            'name', 'subtitle', 'category', 'product_type',
            'description', 'short_description', 'tags',
            'author', 'publisher', 'year', 'language',
            'pages', 'duration', 'isbn',
            'cover_image', 'preview_file', 'digital_file',
            'price', 'price_physical', 'price_digital',
            'stock', 'download_limit', 'download_expiry_hours',
            'status',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Titre du produit',
            }),
            'subtitle': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Sous-titre (optionnel)',
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'product_type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Description complète du produit...',
            }),
            'short_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Résumé court (max 500 caractères)',
            }),
            'tags': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'roman, ivoirien, culture, musique...',
            }),
            'author': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Auteur ou artiste',
            }),
            'publisher': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Maison d\'édition ou label',
            }),
            'year': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '2024',
            }),
            'language': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Français',
            }),
            'pages': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre de pages',
            }),
            'duration': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '45 min',
            }),
            'isbn': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'ISBN (optionnel)',
            }),
            'cover_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'preview_file': forms.FileInput(attrs={
                'class': 'form-control',
            }),
            'digital_file': forms.FileInput(attrs={
                'class': 'form-control',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '5000',
                'min': '0',
            }),
            'price_physical': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '3000',
                'min': '0',
            }),
            'price_digital': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '2000',
                'min': '0',
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0',
                'min': '0',
            }),
            'download_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
            }),
            'download_expiry_hours': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'name':                   'Titre *',
            'subtitle':               'Sous-titre',
            'category':               'Catégorie *',
            'product_type':           'Type de produit *',
            'description':            'Description complète *',
            'short_description':      'Description courte',
            'tags':                   'Mots-clés',
            'author':                 'Auteur / Artiste',
            'publisher':              'Éditeur / Label',
            'year':                   'Année de publication',
            'language':               'Langue',
            'pages':                  'Nombre de pages',
            'duration':               'Durée',
            'isbn':                   'ISBN',
            'cover_image':            'Image de couverture',
            'preview_file':           'Fichier aperçu (extrait gratuit)',
            'digital_file':           'Fichier numérique complet',
            'price':                  'Prix (FCFA) *',
            'price_physical':         'Prix version physique',
            'price_digital':          'Prix version numérique',
            'stock':                  'Stock physique (0 = illimité pour numérique)',
            'download_limit':         'Téléchargements max par achat',
            'download_expiry_hours':  'Expiration du lien (heures)',
            'status':                 'Statut',
        }