"""
IvoirPass V2 — Modèles des événements
"""
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from django.utils import timezone
from django.conf import settings


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
    short_description = models.TextField(
        _('description courte'),
        max_length=500,
        blank=True,
        help_text="Résumé pour les cartes d'aperçu (max 500 car.)"
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
        _('URL vidéo de présentation'),
        blank=True,
        help_text="YouTube ou Vimeo"
    )

    # ============================================
    # BILLETTERIE
    # ============================================
    is_free = models.BooleanField(
        _('événement gratuit'),
        default=False
    )
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
        _('tickets vendus'),
        default=0,
        editable=False
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
        sale_end = self.sale_end or self.start_date
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

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('events:detail', kwargs={'slug': self.slug})


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
        help_text="0 pour gratuit"
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
        default=0
    )

    class Meta:
        verbose_name = _('type de ticket')
        verbose_name_plural = _('types de tickets')
        ordering = ['order', 'price']

    def __str__(self):
        return f"{self.event.title} — {self.name} ({self.price} FCFA)"

    @property
    def is_free(self):
        return self.price == 0

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