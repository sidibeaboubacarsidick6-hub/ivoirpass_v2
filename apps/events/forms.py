"""
IvoirPass V2 — Formulaires des événements
"""
from django import forms
from django.forms import inlineformset_factory
from .models import Event, TicketType, Category


class EventForm(forms.ModelForm):
    """Formulaire principal de création/modification d'événement."""

    class Meta:
        model = Event
        fields = [
            'title', 'subtitle', 'category',
            'description', 'short_description', 'tags',
            'event_type',
            'start_date', 'end_date', 'doors_open',
            'sale_start', 'sale_end',
            'venue_name', 'venue_address', 'venue_city',
            'online_link',
            'cover_image', 'thumbnail', 'video_url',
            'is_free', 'total_capacity',
            'status',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Titre de votre événement',
            }),
            'subtitle': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Sous-titre accrocheur (optionnel)',
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'Décrivez votre événement en détail...',
            }),
            'short_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Résumé court pour les aperçus (max 500 caractères)',
            }),
            'tags': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'musique, concert, afro, abidjan...',
            }),
            'event_type': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'end_date': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'doors_open': forms.TimeInput(
                attrs={'class': 'form-control', 'type': 'time'}
            ),
            'sale_start': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'sale_end': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M'
            ),
            'venue_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Palais de la Culture, Sofitel...',
            }),
            'venue_address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Adresse complète du lieu',
            }),
            'venue_city': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Abidjan',
            }),
            'online_link': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://...',
            }),
            'cover_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'thumbnail': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'video_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://youtube.com/...',
            }),
            'total_capacity': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0 = illimité',
                'min': '0',
            }),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'title':             'Titre de l\'événement *',
            'subtitle':          'Sous-titre',
            'category':          'Catégorie *',
            'description':       'Description complète *',
            'short_description': 'Description courte',
            'tags':              'Mots-clés',
            'event_type':        'Type d\'événement',
            'start_date':        'Date et heure de début *',
            'end_date':          'Date et heure de fin *',
            'doors_open':        'Ouverture des portes',
            'sale_start':        'Début des ventes',
            'sale_end':          'Fin des ventes',
            'venue_name':        'Nom du lieu',
            'venue_address':     'Adresse',
            'venue_city':        'Ville',
            'online_link':       'Lien en ligne',
            'cover_image':       'Image de couverture (1200×600px)',
            'thumbnail':         'Miniature (400×400px)',
            'video_url':         'Vidéo de présentation',
            'is_free':           'Événement gratuit',
            'total_capacity':    'Capacité totale (0 = illimité)',
            'status':            'Statut',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Formate les dates pour le widget datetime-local
        if self.instance.pk:
            for field_name in ['start_date', 'end_date', 'sale_start', 'sale_end']:
                val = getattr(self.instance, field_name, None)
                if val:
                    self.initial[field_name] = val.strftime('%Y-%m-%dT%H:%M')

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end   = cleaned.get('end_date')
        if start and end and end <= start:
            raise forms.ValidationError(
                "La date de fin doit être après la date de début."
            )
        return cleaned


# Formset pour les types de tickets (plusieurs par événement)
TicketTypeFormSet = inlineformset_factory(
    Event,
    TicketType,
    fields=[
        'name', 'description', 'price',
        'quantity', 'max_per_order',
        'sale_start', 'sale_end',
        'is_visible', 'order'
    ],
    widgets={
        'name': forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Ex: VIP, Standard...',
        }),
        'description': forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Description (optionnel)',
        }),
        'price': forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '0',
            'min': '0',
        }),
        'quantity': forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': '0 = illimité',
            'min': '0',
        }),
        'max_per_order': forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'min': '1',
        }),
        'sale_start': forms.DateTimeInput(
            attrs={'class': 'form-control form-control-sm', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M'
        ),
        'sale_end': forms.DateTimeInput(
            attrs={'class': 'form-control form-control-sm', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M'
        ),
        'order': forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'min': '0',
        }),
    },
    extra=1,
    can_delete=True,
)