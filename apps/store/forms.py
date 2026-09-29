"""
IvoirPass V2 — Formulaires de la boutique
"""
from django import forms
from .models import Product, ProductCategory


class ProductForm(forms.ModelForm):
    """Formulaire de création/modification d'un produit."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Le champ `price` a 3 significations selon le type de produit :
        #   - physical : prix version physique
        #   - digital  : prix version numérique
        #   - bundle   : prix TOTAL du bundle (physique + numérique)
        # On adapte le label + placeholder + help pour éviter la confusion
        # (bug UX remonté 2026-09-29 : "Prix *" sans contexte sur bundle).
        product_type = None
        if self.instance and self.instance.pk:
            product_type = self.instance.product_type
        elif self.data.get('product_type'):
            product_type = self.data.get('product_type')

        if product_type == 'bundle':
            self.fields['price'].label = 'Prix bundle complet (physique + numérique) *'
            self.fields['price'].help_text = (
                "Prix total du bundle. Les champs ci-dessous permettent "
                "de définir des prix séparés pour la version physique et "
                "la version numérique seules."
            )
            self.fields['price'].widget.attrs['placeholder'] = '5000'
        elif product_type == 'digital':
            self.fields['price'].label = 'Prix version numérique (FCFA) *'
            self.fields['price'].widget.attrs['placeholder'] = '2000'
        elif product_type == 'physical':
            self.fields['price'].label = 'Prix version physique (FCFA) *'
            self.fields['price'].widget.attrs['placeholder'] = '3000'
        # Si pas de type détecté → on garde le label statique 'Prix (FCFA) *'

    class Meta:
        model  = Product
        fields = [
            'name', 'subtitle', 'category', 'product_type',
            'description', 'short_description', 'tags',
            'author', 'publisher', 'year', 'language',
            'pages', 'duration', 'isbn',
            'cover_image', 'preview_file', 'digital_file', 'external_url',
            'price', 'price_physical', 'price_digital',
            'stock',
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
                'placeholder': 'Ex : +225 07 XX XX XX XX',
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
                'accept': '.jpg,.jpeg,.png,.webp',
            }),
            'preview_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.mp3,.jpg,.jpeg,.png',
            }),
            'digital_file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': (
                    '.mp3,.wav,.flac,.m4a,.aac,.ogg,'
                    '.mp4,.mov,.webm,'
                    '.pdf,.epub,'
                    '.jpg,.jpeg,.png,.webp,'
                    '.zip'
                ),
            }),
            'external_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://open.spotify.com/album/...',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '5000',
                'min': '500',
            }),
            'price_physical': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '3000',
                'min': '500',
            }),
            'price_digital': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '2000',
                'min': '500',
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0',
                'min': '0',
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'name':                   'Titre *',
            'subtitle':               'Sous-titre',
            'category':               'Catégorie *',
            'product_type':           'Type de produit *',
            'description':            'Description complète *',
            'short_description':      'InfoLine',
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
            'external_url':           'Lien externe (album/streaming)',
            'price':                  'Prix (FCFA) *',  # surchargé dynamiquement dans __init__
            'price_physical':         'Prix version physique',
            'price_digital':          'Prix version numérique',
            'stock':                  'Stock physique (0 = illimité pour numérique)',
            'status':                 'Statut',
        }

    def clean(self):
        """
        Validation croisée :
        - Un produit DIGITAL ou BUNDLE doit avoir AU MOINS un mode
          de livraison numérique : soit un fichier uploadé (digital_file),
          soit un lien externe (external_url).
        - Les deux peuvent coexister (external_url est alors prioritaire
          côté téléchargement, pour tracer les clics — voir vue
          guest_download_file).
        """
        cleaned = super().clean()

        product_type = cleaned.get('product_type')
        digital_file = cleaned.get('digital_file') or getattr(self.instance, 'digital_file', None)
        external_url = cleaned.get('external_url') or getattr(self.instance, 'external_url', '')

        if product_type in (Product.ProductType.DIGITAL, Product.ProductType.BUNDLE):
            if not digital_file and not external_url:
                raise forms.ValidationError(
                    "Un produit numérique (ou bundle) doit avoir soit un "
                    "fichier à télécharger, soit un lien externe "
                    "(Spotify, Deezer, Bandcamp...)."
                )

        return cleaned