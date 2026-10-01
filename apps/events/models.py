"""
IvoirPass V2 — Modèles des événements
"""
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, FileExtensionValidator
from django.utils.text import slugify
from django.utils import timezone
from django.conf import settings

# Réutilisation du validateur de taille déjà utilisé dans la boutique
# (évite la duplication et garde une seule source de vérité pour les
# limites de fichiers). Voir apps/store/validators.py.
from apps.store.validators import validate_file_size


class Category(models.Model):
    """
    Catégorie d'événement : Musique, Cinéma, Sport, Théâtre...
    """
    name = models.CharField(_('nom'), max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    icon = models.CharField(
        _('icône Bootstrap'),
        max_length=50,
        default='bi-calendar-event',
        help_text="Classe Bootstrap Icons ex: bi-music-note-beamed"
    )
    color = models.CharField(
        _('couleur'),
        max_length=7,
        default='#1B7A3E',
        help_text="Code hexadécimal ex: #F47920"
    )
    description = models.TextField(_('description'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)
    order = models.PositiveIntegerField(_('ordre d\'affichage'), default=0)

    class Meta:
        verbose_name = _('catégorie')
        verbose_name_plural = _('catégories')
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Event(models.Model):
    """
    Événement IvoirPass.
    Créé par un organisateur, visible publiquement après publication.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Brouillon')
        PUBLISHED = 'published', _('Publié')
        CANCELLED = 'cancelled', _('Annulé')
        COMPLETED = 'completed', _('Terminé')
        POSTPONED = 'postponed', _('Reporté')

    class EventType(models.TextChoices):
        PHYSICAL = 'physical', _('Présentiel')
        ONLINE = 'online', _('En ligne')
        HYBRID = 'hybrid', _('Hybride')

    # ============================================
    # IDENTIFIANTS
    # ============================================
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text="Identifiant public sécurisé"
    )
    slug = models.SlugField(
        max_length=220,
        unique=True,
        blank=True,
        help_text="Généré automatiquement depuis le titre"
    )

    # ============================================
    # INFORMATIONS PRINCIPALES
    # ============================================
    title = models.CharField(_('titre'), max_length=200)
    subtitle = models.CharField(
        _('sous-titre'),
        max_length=300,
        blank=True,
        help_text="Accroche courte affichée sous le titre"
    )
    description = models.TextField(_('description complète'))
    short_description = models.CharField(
        _('InfoLine'),
        max_length=150,
        help_text="Numéro de contact de l'organisateur"
    )

    # ============================================
    # MESSAGE PERSONNALISÉ DANS LES EMAILS DE BILLETS
    # ============================================
    # Texte simple uniquement (pas de HTML) — affiché dans le mail de
    # confirmation d'achat, au-dessus des billets. Optionnel. Voir
    # templates/notifications/email/guest_ticket_confirmed.html.
    custom_message = models.TextField(
        _('message personnalisé'),
        max_length=500,
        blank=True,
        help_text=(
            "Message optionnel ajouté dans l'email de confirmation d'achat "
            "de billets. Ex: « Merci d'avoir acheté ! Rendez-vous bientôt 🌟 ». "
            "Texte simple uniquement (pas de HTML), 500 caractères max."
        ),
    )

    # ============================================
    # CLASSIFICATION
    # ============================================
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name='events',
        verbose_name=_('catégorie')
    )
    tags = models.CharField(
        _('tags'),
        max_length=300,
        blank=True,
        help_text="Mots-clés séparés par des virgules"
    )

    # ============================================
    # ORGANISATEUR
    # ============================================
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name=_('organisateur'),
        limit_choices_to={'role': 'organizer'}
    )

    # Agents scanner explicitement assignés à cet événement par
    # l'organisateur. Un compte avec le rôle 'scanner' non assigné à un
    # événement ne peut plus le scanner (voir apps/scanner/views.py et
    # apps/scanner/api/views.py) — avant, tout agent scanner pouvait
    # scanner n'importe quel événement publié sur la plateforme.
    scanner_agents = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='assigned_events',
        blank=True,
        limit_choices_to={'role': 'scanner'},
        verbose_name=_('agents scanner assignés'),
    )

    # ============================================
    # DATES ET HORAIRES
    # ============================================
    start_date = models.DateTimeField(_('date de début'))
    end_date = models.DateTimeField(_('date de fin'))
    doors_open = models.TimeField(
        _('ouverture des portes'),
        null=True,
        blank=True,
        help_text="Heure d'ouverture avant l'événement"
    )
    sale_start = models.DateTimeField(
        _('début des ventes'),
        null=True,
        blank=True,
        help_text="Laisser vide pour démarrer immédiatement à la publication"
    )
    sale_end = models.DateTimeField(
        _('fin des ventes'),
        null=True,
        blank=True,
        help_text="Laisser vide pour fermer à la date de début"
    )

    # ============================================
    # LIEU
    # ============================================
    event_type = models.CharField(
        _('type d\'événement'),
        max_length=20,
        choices=EventType.choices,
        default=EventType.PHYSICAL
    )
    venue_name = models.CharField(
        _('nom du lieu'),
        max_length=200,
        blank=True,
        help_text="Ex: Palais de la Culture, Sofitel Abidjan..."
    )
    venue_address = models.TextField(_('adresse complète'), blank=True)
    venue_city = models.CharField(
        _('ville'),
        max_length=100,
        default='Abidjan'
    )
    venue_country = models.CharField(
        _('pays'),
        max_length=100,
        default='Côte d\'Ivoire'
    )
    venue_latitude = models.DecimalField(
        _('latitude'),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    venue_longitude = models.DecimalField(
        _('longitude'),
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )
    online_link = models.URLField(
        _('lien en ligne'),
        blank=True,
        help_text="URL du stream ou de la conférence en ligne"
    )

    # ============================================
    # MÉDIAS
    # ============================================
    cover_image = models.ImageField(
        _('image de couverture'),
        upload_to='events/covers/%Y/%m/',
        null=True,
        blank=True,
        help_text="Taille recommandée : 1200×600px"
    )
    thumbnail = models.ImageField(
        _('miniature'),
        upload_to='events/thumbnails/%Y/%m/',
        null=True,
        blank=True,
        help_text="Taille recommandée : 400×400px"
    )
    video_url = models.URLField(
        _('URL vidéo (YouTube/Vimeo)'),
        blank=True,
        help_text=(
            "Lien YouTube ou Vimeo. OU uploadez un fichier mp4 ci-dessous. "
            "Si les deux sont renseignés, le fichier uploadé est prioritaire."
        )
    )
    video_file = models.FileField(
        _('fichier vidéo (mp4)'),
        upload_to='events/videos/%Y/%m/',
        null=True,
        blank=True,
        help_text=(
            "Fichier vidéo mp4, 100 Mo maximum. OU renseignez un lien "
            "YouTube/Vimeo ci-dessus."
        ),
        validators=[
            FileExtensionValidator(['mp4']),
            validate_file_size(100),
        ],
    )

    # ============================================
    # BILLETTERIE
    # ============================================
    min_price = models.DecimalField(
        _('prix minimum'),
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Calculé automatiquement depuis les types de tickets"
    )
    total_capacity = models.PositiveIntegerField(
        _('capacité totale'),
        default=0,
        help_text="0 = illimité"
    )
    tickets_sold = models.PositiveIntegerField(
        _('billets vendus'),
        default=0,
        editable=False
    )
    # ============================================
    # 🎫 TICKETS GRATUITS (Vague 2.2 — 2026-09-30)
    # L'organisateur peut générer des codes de billets gratuits
    # nominatifs, dans la limite du quota. Au-delà, validation admin MKS.
    # ============================================
    free_tickets_quota = models.PositiveIntegerField(
        _('quota billets gratuits'),
        default=20,
        help_text=(
            "Nombre maximum de codes gratuits que l'organisateur peut "
            "générer pour cet événement. Au-delà, une validation admin "
            "est nécessaire."
        )
    )
    free_tickets_generated = models.PositiveIntegerField(
        _('codes gratuits générés'),
        default=0,
        editable=False,
        help_text="Compteur interne — mis à jour à chaque génération."
    )

    # ============================================
    # STATUT
    # ============================================
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    is_featured = models.BooleanField(
        _('mis en avant'),
        default=False,
        help_text="Affiché en priorité sur la page d'accueil"
    )

    # ============================================
    # COMMISSION PLATEFORME (dynamique)
    # ============================================
    commission_rate = models.DecimalField(
        _('taux de commission (%)'),
        max_digits=5,
        decimal_places=2,
        default=8.00,
        help_text="Pourcentage prélevé sur l'organisateur. Ex: 8.00 = 8%"
    )
    commission_negotiated = models.BooleanField(
        _('commission négociée'),
        default=False,
        help_text="True si l'admin a défini un taux personnalisé"
    )
    commission_note = models.TextField(
        _('note de commission'),
        blank=True,
        help_text="Raison de la commission personnalisée"
    )

    requires_approval = models.BooleanField(
        _('inscription sur approbation'),
        default=False
    )

    requires_approval = models.BooleanField(
        _('inscription sur approbation'),
        default=False
    )

    # ============================================
    # 🗓️ VAGUE 4 — ÉVÉNEMENT MULTI-JOURS
    # ============================================
    # Marqueur explicite : True si l'événement a été créé via le tunnel
    # multi-jours. Permet de :
    #  - afficher/regrouper les billets par jour sur la landing
    #  - adapter le scanner (1 scan par jour au lieu de 1 seul)
    #  - filtrer dans l'admin
    #
    # Les événements existants restent à False (comportement legacy).
    is_multi_day = models.BooleanField(
        _('événement multi-jours'),
        default=False,
        help_text=(
            "Coché automatiquement quand l'événement est créé via le "
            "tunnel multi-jours. Active la validation 1 scan par jour."
        ),
    )

    # ============================================
    # DATES SYSTÈME
    # ============================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('événement')
        verbose_name_plural = _('événements')
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status', 'start_date']),
            models.Index(fields=['organizer', 'status']),
            models.Index(fields=['is_featured', 'status']),
        ]

    def __str__(self):
        return f"{self.title} — {self.start_date.strftime('%d/%m/%Y')}"

    def save(self, *args, **kwargs):
        # Génère le slug depuis le titre
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        # Enregistre la date de publication
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Vague 4 : bug — Django's collector ne ramasse pas les EventDay
        liés lors de la suppression de l'Event (interaction FK
        DEFERRABLE + M2M restaurée manuellement).

        On les supprime manuellement avant le super().delete().
        """
        # Supprime d'abord les EventDay (les M2M through + ScanLog.event_day
        # passent en CASCADE / SET_NULL automatiquement côté DB).
        self.event_days.all().delete()
        return super().delete(*args, **kwargs)

    def generate_event_days(self):
        """
        Génère les EventDays manquants depuis start_date / end_date.

        Appelée manuellement par le tunnel multi-jours (étape 2).
        Ne supprime PAS les jours existants (l'organisateur peut les
        renommer ou en ajouter), se contente d'ajouter les manquants.

        Vague 4 — 2026-09-30.
        """
        from datetime import timedelta

        if not (self.start_date and self.end_date):
            return

        start = self.start_date.date()
        end = self.end_date.date()

        # Liste des dates attendues (1 par jour inclus)
        expected_dates = []
        cur = start
        while cur <= end:
            expected_dates.append(cur)
            cur += timedelta(days=1)

        # Jours déjà existants (par date)
        existing_dates = set(self.event_days.values_list('date', flat=True))

        # Crée les jours manquants
        for i, d in enumerate(expected_dates, start=1):
            if d not in existing_dates:
                EventDay.objects.create(
                    event=self, date=d, order=i,
                )

    # ============================================
    # PROPRIÉTÉS UTILES
    # ============================================
    @property
    def is_upcoming(self):
        return self.start_date > timezone.now()

    @property
    def is_ongoing(self):
        now = timezone.now()
        return self.start_date <= now <= self.end_date

    @property
    def is_past(self):
        return self.end_date < timezone.now()

    @property
    def is_on_sale(self):
        now = timezone.now()
        if self.status != self.Status.PUBLISHED:
            return False
        sale_start = self.sale_start or self.published_at or now
        # Vente ouverte jusqu'à la FIN de l'événement (pas le début) :
        # l'acheteur peut encore prendre un billet pendant l'événement.
        sale_end = self.sale_end or self.end_date
        return sale_start <= now <= sale_end

    @property
    def tickets_remaining(self):
        if self.total_capacity == 0:
            return None  # Illimité
        return max(0, self.total_capacity - self.tickets_sold)

    @property
    def is_sold_out(self):
        if self.total_capacity == 0:
            return False
        return self.tickets_remaining == 0

    @property
    def occupancy_rate(self):
        """Taux de remplissage en pourcentage."""
        if self.total_capacity == 0:
            return 0
        return round((self.tickets_sold / self.total_capacity) * 100, 1)

    @property
    def video_embed_url(self):
        """
        URL exploitable pour afficher la vidéo de présentation.

        - Si un fichier mp4 est uploadé → URL du fichier (balise <video>).
        - Sinon si video_url pointe vers YouTube/Vimeo → URL embed
          (balise <iframe>).
        - Sinon → l'URL brute (le template fera un lien simple).
        - Si aucune vidéo → None.

        Le fichier uploadé est prioritaire sur le lien externe.
        """
        import re

        # 1) Fichier uploadé prioritaire
        if self.video_file:
            try:
                return self.video_file.url
            except ValueError:
                # Fichier référencé en base mais absent du storage
                return None

        # 2) Lien externe YouTube / Vimeo
        url = (self.video_url or '').strip()
        if not url:
            return None

        # YouTube : youtu.be/ID, youtube.com/watch?v=ID, /embed/ID, /shorts/ID
        yt = re.search(
            r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([A-Za-z0-9_-]{6,})',
            url,
        )
        if yt:
            return f'https://www.youtube.com/embed/{yt.group(1)}'

        # Vimeo : vimeo.com/ID, vimeo.com/video/ID
        vm = re.search(r'vimeo\.com/(?:video/)?(\d+)', url)
        if vm:
            return f'https://player.vimeo.com/video/{vm.group(1)}'

        # 3) Fallback : URL brute
        return url

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('events:detail', kwargs={'slug': self.slug})

class EventDay(models.Model):
    """
    Jour d'un événement multi-jours (Vague 4 — 2026-09-30).

    Un événement peut avoir plusieurs EventDays. Un TicketType peut être
    lié à 1 ou N EventDays :
      - 1 EventDay  → billet 1 jour (ex. « Vendredi soir »)
      - N EventDays → pass multi-jours (ex. « Pass 3 jours »)

    Un TicketType sans EventDay = billet legacy (1 scan définitif, pas
    de contrainte de date). Le mode multi-jours ne s'active QUE si au
    moins 1 EventDay est lié au TicketType.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='event_days',
        verbose_name=_('événement'),
    )
    date = models.DateField(
        _('date'),
        help_text="Jour concerné par ce créneau.",
    )
    name = models.CharField(
        _('nom du jour'),
        max_length=100,
        blank=True,
        help_text=(
            "Optionnel. Ex : « Soirée d'ouverture », « Finale ». "
            "Si vide, la date sera utilisée comme nom."
        ),
    )
    doors_open = models.TimeField(
        _('ouverture des portes'),
        null=True,
        blank=True,
        help_text="Heure d'ouverture des portes (optionnel).",
    )
    order = models.PositiveIntegerField(
        _("ordre d'affichage"),
        default=0,
        help_text="Ordre croissant. Les jours s'affichent dans cet ordre.",
    )

    class Meta:
        verbose_name = _("jour d'événement")
        verbose_name_plural = _("jours d'événement")
        ordering = ['order', 'date']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'date'],
                name='unique_event_day_per_date',
            ),
        ]

    def __str__(self):
        label = self.name or self.date.strftime('%d/%m/%Y')
        return f"{self.event.title} — {label}"

    @property
    def display_name(self):
        """Nom affiché : name personnalisé ou date formatée."""
        if self.name:
            return self.name
        return self.date.strftime('%A %d %B %Y').capitalize()




class TicketType(models.Model):
    """
    Type de ticket pour un événement.
    Ex : VIP, Standard, Étudiant, Early Bird...
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='ticket_types',
        verbose_name=_('événement')
    )
    name = models.CharField(
        _('nom'),
        max_length=100,
        help_text="Ex: VIP, Standard, Étudiant, Early Bird"
    )
    description = models.TextField(_('description'), blank=True)
    price = models.DecimalField(
        _('prix (FCFA)'),
        max_digits=10,
        decimal_places=0,
        validators=[MinValueValidator(100)],
        help_text="Minimum 100 FCFA"
    )
    valid_date = models.DateField(
        _('jour de validité'),
        null=True,
        blank=True,
        help_text=(
            "Si l'événement dure plusieurs jours et que ce ticket ne "
            "donne accès qu'à un jour précis (ex: samedi), indiquez-le ici. "
            "Laisser vide si le ticket est valable sur toute la durée de l'événement."
        )
    )
    quantity = models.PositiveIntegerField(
        _('quantité disponible'),
        default=0,
        help_text="0 = illimité"
    )
    quantity_sold = models.PositiveIntegerField(
        _('quantité vendue'),
        default=0,
        editable=False
    )
    max_per_order = models.PositiveIntegerField(
        _('maximum par commande'),
        default=10
    )
    sale_start = models.DateTimeField(
        _('début vente'),
        null=True,
        blank=True
    )
    sale_end = models.DateTimeField(
        _('fin vente'),
        null=True,
        blank=True
    )
    is_visible = models.BooleanField(
        _('visible'),
        default=True
    )
    order = models.PositiveIntegerField(
        _('ordre d\'affichage'),
        default=0,
        blank=True,
    )
    # ── Vague 4 : jours couverts par ce type de ticket ──────────────
    # Vide = billet legacy (1 scan définitif). Non vide = 1 scan par
    # jour couvert (billet 1 jour ou pass multi-jours).
    event_days = models.ManyToManyField(
        EventDay,
        blank=True,
        related_name='ticket_types',
        verbose_name=_('jours couverts'),
        help_text=(
            "Laisser vide pour un billet classique (1 scan définitif). "
            "Sélectionner 1 jour = billet 1 jour. "
            "Sélectionner N jours = pass multi-jours (1 scan par jour)."
        ),
    )

    class Meta:
        verbose_name = _('type de ticket')
        verbose_name_plural = _('types de tickets')
        ordering = ['order', 'price']

    def __str__(self):
        return f"{self.event.title} — {self.name} ({self.price} FCFA)"


    @property
    def remaining(self):
        if self.quantity == 0:
            return None
        return max(0, self.quantity - self.quantity_sold)

    @property
    def is_sold_out(self):
        if self.quantity == 0:
            return False
        return self.remaining == 0

    @property
    def is_available(self):
        """Ce ticket est-il disponible à la vente ?"""
        if not self.is_visible or self.is_sold_out:
            return False
        now = timezone.now()
        if self.sale_start and now < self.sale_start:
            return False
        if self.sale_end and now > self.sale_end:
            return False
        return True

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()

        if self.price is not None and self.price < 100:
            raise ValidationError({
                'price': "Le prix minimum est de 100 FCFA."
            })

        if self.valid_date and self.event_id:
            event_start = self.event.start_date.date()
            event_end = self.event.end_date.date()
            if not (event_start <= self.valid_date <= event_end):
                raise ValidationError({
                    'valid_date': f"Cette date doit être comprise entre le "
                                   f"{event_start.strftime('%d/%m/%Y')} et le "
                                   f"{event_end.strftime('%d/%m/%Y')}."
                })


class EventFAQ(models.Model):
    """
    Question fréquente affichée sur la landing page d'un événement.
    Ex: "Puis-je me faire rembourser ?", "Le lieu est-il accessible en PMR ?"
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='faqs',
        verbose_name=_('événement')
    )
    question = models.CharField(_('question'), max_length=300)
    answer = models.TextField(_('réponse'))
    order = models.PositiveIntegerField(_('ordre d\'affichage'), default=0)


    class Meta:
        verbose_name = _('question fréquente')
        verbose_name_plural = _('questions fréquentes')
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.event.title} — {self.question}"


class EventGalleryItem(models.Model):
    """
    Élément de la galerie / programme d'un événement.

    Un seul modèle sert les deux usages pour rester simple : une photo de
    galerie (avec `image`, sans `time`) et une entrée de programme/lineup
    (avec `time` et éventuellement `subtitle` pour l'intervenant, sans
    `image` obligatoire) se distinguent seulement par les champs
    renseignés, pas par des tables séparées.
    """
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='gallery_items',
        verbose_name=_('événement')
    )
    image = models.ImageField(
        _('image'),
        upload_to='events/gallery/%Y/%m/',
        null=True, blank=True,
        help_text="Laisser vide pour une entrée de programme sans visuel."
    )
    title = models.CharField(
        _('titre'),
        max_length=200,
        blank=True,
        help_text="Légende de la photo, ou titre du passage (ex: 'Concert live')."
    )
    subtitle = models.CharField(
        _('sous-titre'),
        max_length=200,
        blank=True,
        help_text="Ex: nom de l'artiste/intervenant pour une entrée de programme."
    )
    time = models.TimeField(
        _('heure'),
        null=True, blank=True,
        help_text="Renseigné uniquement pour une entrée de programme (ex: 20h00)."
    )
    order = models.PositiveIntegerField(
        _('ordre d\'affichage'),
        default=0,
        blank=True
    )


    class Meta:
        verbose_name = _('élément galerie / programme')
        verbose_name_plural = _('galerie / programme')
        ordering = ['order', 'time', 'id']

    def __str__(self):
        return f"{self.event.title} — {self.title or self.subtitle or '#' + str(self.pk)}"

    @property
    def is_program_entry(self):
        """Distingue une entrée de programme (a une heure) d'une simple photo."""
        return self.time is not None


class EventPartner(models.Model):
    """Partenaire / sponsor affiché sur la landing page d'un événement."""
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='partners',
        verbose_name=_('événement')
    )
    name = models.CharField(_('nom'), max_length=150)
    logo = models.ImageField(
        _('logo'),
        upload_to='events/partners/%Y/%m/',
        null=True, blank=True,
    )
    website_url = models.URLField(_('site web'), blank=True)
    order = models.PositiveIntegerField(_('ordre d\'affichage'), default=0)


    class Meta:
        verbose_name = _('partenaire')
        verbose_name_plural = _('partenaires')
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.event.title} — {self.name}"
