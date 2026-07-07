"""
IvoirPass V2 — Boutique Culturelle
Livres, Albums, Produits numériques
"""
import uuid
import os
import random
import string
import logging
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from django.utils import timezone

logger = logging.getLogger(__name__)


class ProductCategory(models.Model):
    """Catégorie de produit culturel."""
    name = models.CharField(_('nom'), max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    icon = models.CharField(
        _('icône'),
        max_length=50,
        default='bi-bag',
        help_text="Classe Bootstrap Icons"
    )
    description = models.TextField(_('description'), blank=True)
    is_active = models.BooleanField(_('active'), default=True)
    order = models.PositiveIntegerField(_('ordre'), default=0)

    class Meta:
        verbose_name = _('catégorie produit')
        verbose_name_plural = _('catégories produits')
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Product(models.Model):
    """
    Produit culturel IvoirPass.
    Peut être physique, numérique ou les deux (bundle).
    """

    class ProductType(models.TextChoices):
        PHYSICAL = 'physical', _('Physique (livraison)')
        DIGITAL = 'digital', _('Numérique (téléchargement)')
        BUNDLE = 'bundle', _('Bundle (physique + numérique)')

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Brouillon')
        PUBLISHED = 'published', _('Publié')
        OUT_STOCK = 'out_stock', _('Rupture de stock')
        ARCHIVED = 'archived', _('Archivé')

    # Identifiants
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    slug = models.SlugField(
        max_length=220,
        unique=True,
        blank=True
    )

    # Informations principales
    name = models.CharField(_('nom'), max_length=200)
    subtitle = models.CharField(
        _('sous-titre'),
        max_length=300,
        blank=True
    )
    description = models.TextField(_('description'))
    short_description = models.TextField(
        _('description courte'),
        max_length=500,
        blank=True
    )

    # Classification
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products',
        verbose_name=_('catégorie')
    )
    product_type = models.CharField(
        _('type de produit'),
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.PHYSICAL
    )
    tags = models.CharField(
        _('tags'),
        max_length=300,
        blank=True
    )

    # Vendeur
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name=_('vendeur')
    )

    # Médias
    cover_image = models.ImageField(
        _('image de couverture'),
        upload_to='store/covers/%Y/%m/',
        null=True,
        blank=True
    )
    preview_file = models.FileField(
        _('fichier aperçu'),
        upload_to='store/previews/%Y/%m/',
        null=True,
        blank=True,
        help_text="Extrait gratuit (PDF, MP3...)"
    )
    digital_file = models.FileField(
        _('fichier numérique'),
        upload_to='store/digital/%Y/%m/',
        null=True,
        blank=True,
        help_text="Fichier complet — non accessible publiquement"
    )

    # Métadonnées produit
    author = models.CharField(_('auteur/artiste'), max_length=200, blank=True)
    publisher = models.CharField(_('éditeur/label'), max_length=200, blank=True)
    year = models.PositiveIntegerField(_('année'), null=True, blank=True)
    language = models.CharField(
        _('langue'),
        max_length=50,
        blank=True,
        default='Français'
    )
    pages = models.PositiveIntegerField(
        _('nombre de pages'),
        null=True,
        blank=True,
        help_text="Pour les livres"
    )
    duration = models.CharField(
        _('durée'),
        max_length=20,
        blank=True,
        help_text="Pour les albums (ex: 45 min)"
    )
    isbn = models.CharField(_('ISBN'), max_length=20, blank=True)

    # Prix et stock
    price = models.DecimalField(
        _('prix (FCFA)'),
        max_digits=10,
        decimal_places=0
    )
    price_physical = models.DecimalField(
        _('prix version physique'),
        max_digits=10,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Pour les bundles : prix partie physique"
    )
    price_digital = models.DecimalField(
        _('prix version numérique'),
        max_digits=10,
        decimal_places=0,
        null=True,
        blank=True,
        help_text="Pour les bundles : prix partie numérique"
    )
    stock = models.PositiveIntegerField(
        _('stock physique'),
        default=0,
        help_text="0 pour produits numériques (illimité)"
    )
    sold_count = models.PositiveIntegerField(
        _('exemplaires vendus'),
        default=0,
        editable=False
    )

    # Téléchargement
    download_limit = models.PositiveIntegerField(
        _('limite de téléchargements'),
        default=3,
        help_text="Nombre max de téléchargements par achat"
    )
    download_expiry_hours = models.PositiveIntegerField(
        _('expiration lien (heures)'),
        default=48
    )

    # Statut
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT
    )
    is_featured = models.BooleanField(
        _('mis en avant'),
        default=False
    )

    # ============================================
    # COMMISSION PLATEFORME
    # ============================================
    commission_rate = models.DecimalField(
        _('taux de commission (%)'),
        max_digits=5,
        decimal_places=2,
        default=8.00,
        help_text="Commission IvoirPass prélevée sur le vendeur"
    )
    commission_negotiated = models.BooleanField(
        _('commission négociée'),
        default=False
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('produit')
        verbose_name_plural = _('produits')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status', 'product_type']),
            models.Index(fields=['seller', 'status']),
        ]

    def __str__(self):
        return f"{self.name} — {self.seller.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Product.objects.filter(
                slug=slug
            ).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('store:detail', kwargs={'slug': self.slug})

    @property
    def is_digital(self):
        return self.product_type in [
            self.ProductType.DIGITAL,
            self.ProductType.BUNDLE
        ]

    @property
    def is_physical(self):
        return self.product_type in [
            self.ProductType.PHYSICAL,
            self.ProductType.BUNDLE
        ]

    @property
    def is_available(self):
        if self.status != self.Status.PUBLISHED:
            return False
        if self.is_physical and self.stock == 0:
            return False
        return True

    @property
    def file_extension(self):
        """Extension du fichier numérique."""
        if self.digital_file:
            _, ext = os.path.splitext(self.digital_file.name)
            return ext.upper().lstrip('.')
        return ''

    @property
    def file_size_mb(self):
        """Taille du fichier numérique en Mo."""
        if self.digital_file:
            try:
                size = self.digital_file.size
                return round(size / (1024 * 1024), 1)
            except Exception:
                return 0
        return 0


class ProductOrder(models.Model):
    """
    Commande d'un produit culturel.
    Séparée des commandes de tickets.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('En attente de paiement')
        PAID = 'paid', _('Payée')
        SHIPPED = 'shipped', _('Expédiée')
        DELIVERED = 'delivered', _('Livrée')
        CANCELLED = 'cancelled', _('Annulée')
        REFUNDED = 'refunded', _('Remboursée')

    class DeliveryMethod(models.TextChoices):
        DOWNLOAD = 'download', _('Téléchargement numérique')
        DELIVERY = 'delivery', _('Livraison physique')

    # Numéro unique
    order_number = models.CharField(
        _('numéro de commande'),
        max_length=25,
        unique=True,
        blank=True
    )
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )

    # Relations
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_orders',
        verbose_name=_('acheteur')
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name=_('produit')
    )

    # Commande
    quantity = models.PositiveIntegerField(_('quantité'), default=1)
    unit_price = models.DecimalField(
        _('prix unitaire'),
        max_digits=10,
        decimal_places=0
    )
    subtotal = models.DecimalField(
        _('sous-total'),
        max_digits=12,
        decimal_places=0
    )
    commission = models.DecimalField(
        _('commission IvoirPass'),
        max_digits=10,
        decimal_places=0,
        default=0
    )
    total = models.DecimalField(
        _('total'),
        max_digits=12,
        decimal_places=0
    )

    # ============================================
    # LIVRAISON
    # ============================================
    delivery_method = models.CharField(
        _('méthode de livraison'),
        max_length=20,
        choices=DeliveryMethod.choices,
        default=DeliveryMethod.DOWNLOAD
    )
    delivery_name = models.CharField(
        _('nom destinataire'),
        max_length=200,
        blank=True
    )
    delivery_phone = models.CharField(
        _('téléphone'),
        max_length=20,
        blank=True
    )
    delivery_address = models.TextField(
        _('adresse complète'),
        blank=True
    )
    delivery_city = models.CharField(
        _('ville'),
        max_length=100,
        blank=True
    )
    delivery_commune = models.CharField(
        _('commune'),
        max_length=100,
        blank=True
    )
    delivery_country = models.CharField(
        _('pays'),
        max_length=100,
        blank=True,
        default="Côte d'Ivoire"
    )
    delivery_instructions = models.TextField(
        _('instructions'),
        blank=True
    )
    tracking_number = models.CharField(
        _('numéro de suivi'),
        max_length=100,
        blank=True
    )

    # Paiement
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    payment_method = models.CharField(max_length=50, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('commande produit')
        verbose_name_plural = _('commandes produits')
        ordering = ['-created_at']

    def __str__(self):
        return (
            f"Commande {self.order_number} — "
            f"{self.product.name} — "
            f"{self.buyer.email}"
        )

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_number()
        if not self.subtotal:
            self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def _generate_number(self):
        suffix = ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=6)
        )
        return f"ST-{timezone.now().year}-{suffix}"

    def mark_as_paid(self, payment_method='', payment_reference=''):
        """
        Confirme la commande et génère les liens de téléchargement.
        Notifie le vendeur pour les produits physiques.
        """
        self.status = self.Status.PAID
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.paid_at = timezone.now()
        self.save()

        # Crédite le wallet du vendeur
        self._credit_seller_wallet()

        # Génère les liens de téléchargement si produit numérique
        if self.product.is_digital:
            self._generate_download_links()

        # Met à jour le stock si produit physique
        if self.product.is_physical:
            from django.db import transaction
            from django.db.models import F
            
            with transaction.atomic():
                # Verrouille et décrémente de manière atomique
                updated = Product.objects.select_for_update().filter(
                    pk=self.product.pk,
                    stock__gte=self.quantity
                ).update(
                    stock=F('stock') - self.quantity,
                    sold_count=F('sold_count') + self.quantity
                )
                
                if not updated:
                    logger.error(f"Stock insuffisant pour {self.order_number}")
                    raise ValueError("Stock insuffisant")

            # ✅ Notifie le vendeur qu'il doit préparer une livraison
            try:
                from apps.notifications.service import NotificationService
                NotificationService.notify_seller_new_order(self, is_guest=False)
                logger.info(
                    f"Vendeur notifié pour la commande {self.order_number} "
                    f"(produit physique)"
                )
            except Exception as e:
                logger.error(
                    f"Erreur notification vendeur pour commande {self.order_number}: {e}"
                )

    def _credit_seller_wallet(self):
        """Crédite le wallet avec la commission dynamique du produit — anti-doublon."""
        from apps.dashboard.models import OrganizerWallet, WalletTransaction

        # ✅ Anti-doublon : ne crédite jamais deux fois la même commande
        already_credited = WalletTransaction.objects.filter(
            reference=self.order_number
        ).exists()
        if already_credited:
            logger.info(
                f"Transaction déjà créditée pour la commande {self.order_number}, ignorée"
            )
            return

        commission_rate = float(self.product.commission_rate) / 100
        net_amount = int(round(float(self.subtotal) * (1 - commission_rate)))

        wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.product.seller
        )
        wallet.credit(
            amount=net_amount,
            description=f"Vente boutique — {self.product.name}",
            reference=self.order_number,
        )
        logger.info(
            f"Wallet crédité pour la commande {self.order_number}: "
            f"{net_amount} FCFA"
        )

    def _generate_download_links(self):
        """Génère les liens de téléchargement sécurisés."""
        for i in range(self.quantity):
            DownloadLink.objects.create(
                order=self,
                product=self.product,
                max_downloads=self.product.download_limit,
                expires_at=timezone.now() + timezone.timedelta(
                    hours=self.product.download_expiry_hours
                )
            )
        logger.info(
            f"{self.quantity} lien(s) de téléchargement généré(s) pour "
            f"la commande {self.order_number}"
        )

    def cancel(self):
        """Annule la commande et restaure le stock si nécessaire."""
        if self.status in [self.Status.PENDING, self.Status.PAID]:
            self.status = self.Status.CANCELLED
            self.save()
            
            # Restaurer le stock si commande était payée
            if self.product.is_physical and self.status == self.Status.PAID:
                self.product.stock += self.quantity
                self.product.save(update_fields=['stock'])
                logger.info(
                    f"Stock restauré pour la commande annulée {self.order_number}"
                )

    def refund(self):
        """Rembourse la commande."""
        if self.status == self.Status.PAID:
            self.status = self.Status.REFUNDED
            self.save()
            
            # Restaurer le stock si produit physique
            if self.product.is_physical:
                self.product.stock += self.quantity
                self.product.save(update_fields=['stock'])
                logger.info(
                    f"Stock restauré pour la commande remboursée {self.order_number}"
                )


class DownloadLink(models.Model):
    """
    Lien de téléchargement sécurisé et temporaire.
    Chaque achat génère un lien unique avec expiration.
    """
    token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    order = models.ForeignKey(
        ProductOrder,
        on_delete=models.CASCADE,
        related_name='download_links',
        verbose_name=_('commande')
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='download_links',
        verbose_name=_('produit')
    )
    download_count = models.PositiveIntegerField(
        _('téléchargements effectués'),
        default=0
    )
    max_downloads = models.PositiveIntegerField(
        _('limite de téléchargements'),
        default=3
    )
    expires_at = models.DateTimeField(_('expire le'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('lien de téléchargement')
        verbose_name_plural = _('liens de téléchargement')

    def __str__(self):
        return f"Lien {self.token} — {self.product.name}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_exhausted(self):
        return self.download_count >= self.max_downloads

    @property
    def is_valid(self):
        return not self.is_expired and not self.is_exhausted

    @property
    def downloads_remaining(self):
        return max(0, self.max_downloads - self.download_count)


# ============================================
# NOUVEAUX MODÈLES POUR COMMANDES INVITÉS
# ============================================

class GuestProductOrder(models.Model):
    """
    Commande boutique passée sans compte.
    Un client peut commander le même produit autant de fois qu'il le souhaite.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', _('En attente de paiement')
        PAID = 'paid', _('Payée')
        SHIPPED = 'shipped', _('Expédiée')
        DELIVERED = 'delivered', _('Livrée')
        CANCELLED = 'cancelled', _('Annulée')
        REFUNDED = 'refunded', _('Remboursée')

    class DeliveryMethod(models.TextChoices):
        DOWNLOAD = 'download', _('Téléchargement')
        DELIVERY = 'delivery', _('Livraison')

    # Numéro unique
    order_number = models.CharField(
        _('numéro de commande'),
        max_length=25,
        unique=True,
        blank=True
    )
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )

    # Infos acheteur (sans compte)
    first_name = models.CharField(_('prénom'), max_length=100)
    last_name = models.CharField(_('nom'), max_length=100)
    email = models.EmailField(_('email'))
    phone = models.CharField(_('téléphone'), max_length=20, blank=True)

    # Produit
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='guest_orders',
        verbose_name=_('produit')
    )
    quantity = models.PositiveIntegerField(_('quantité'), default=1)

    # Prix
    unit_price = models.DecimalField(
        _('prix unitaire'),
        max_digits=10,
        decimal_places=0
    )
    subtotal = models.DecimalField(
        _('sous-total'),
        max_digits=12,
        decimal_places=0
    )
    total = models.DecimalField(
        _('total'),
        max_digits=12,
        decimal_places=0
    )

    # Livraison
    delivery_method = models.CharField(
        _('méthode de livraison'),
        max_length=20,
        choices=DeliveryMethod.choices,
        default=DeliveryMethod.DOWNLOAD
    )
    delivery_name = models.CharField(
        _('nom destinataire'),
        max_length=200,
        blank=True
    )
    delivery_phone = models.CharField(
        _('téléphone'),
        max_length=20,
        blank=True
    )
    delivery_address = models.TextField(
        _('adresse complète'),
        blank=True
    )
    delivery_city = models.CharField(
        _('ville'),
        max_length=100,
        blank=True
    )
    delivery_commune = models.CharField(
        _('commune'),
        max_length=100,
        blank=True
    )
    delivery_country = models.CharField(
        _('pays'),
        max_length=100,
        blank=True,
        default="Côte d'Ivoire"
    )
    delivery_instructions = models.TextField(
        _('instructions'),
        blank=True
    )
    tracking_number = models.CharField(
        _('numéro de suivi'),
        max_length=100,
        blank=True
    )

    # Statut et paiement
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    payment_method = models.CharField(
        _('méthode de paiement'),
        max_length=50,
        blank=True
    )
    payment_reference = models.CharField(
        _('référence de paiement'),
        max_length=200,
        blank=True
    )
    paid_at = models.DateTimeField(
        _('payé le'),
        null=True,
        blank=True
    )

    # Dates
    created_at = models.DateTimeField(
        _('créé le'),
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        _('modifié le'),
        auto_now=True
    )
    shipped_at = models.DateTimeField(
        _('expédié le'),
        null=True,
        blank=True
    )
    delivered_at = models.DateTimeField(
        _('livré le'),
        null=True,
        blank=True
    )

    class Meta:
        verbose_name = _('commande boutique invité')
        verbose_name_plural = _('commandes boutique invités')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'status']),
            models.Index(fields=['product', 'status']),
            models.Index(fields=['order_number']),
        ]

    def __str__(self):
        return f"Commande {self.order_number} — {self.email}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            suffix = ''.join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            self.order_number = f"ST-{timezone.now().year}-{suffix}"
        if not self.subtotal:
            self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    @property
    def buyer_name(self):
        """Nom complet de l'acheteur."""
        return f"{self.first_name} {self.last_name}".strip()

    def mark_as_paid(self, payment_method='', payment_reference=''):
        """
        Confirme le paiement. Génère TOUJOURS de nouveaux liens de téléchargement,
        indépendamment des achats précédents du même produit par le même client.
        Notifie le vendeur pour les produits physiques.
        """
        self.status = self.Status.PAID
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.paid_at = timezone.now()
        self.save()

        # Crédite le wallet du vendeur
        self._credit_seller_wallet()

        # Génère les liens de téléchargement si produit numérique
        if self.product.is_digital:
            self._generate_download_links()

        # Met à jour le stock si produit physique
        if self.product.is_physical:
            from django.db import transaction
            from django.db.models import F
            
            with transaction.atomic():
                updated = Product.objects.select_for_update().filter(
                    pk=self.product.pk,
                    stock__gte=self.quantity
                ).update(
                    stock=F('stock') - self.quantity,
                    sold_count=F('sold_count') + self.quantity
                )
                
                if not updated:
                    logger.error(f"Stock insuffisant pour guest {self.order_number}")
                    raise ValueError("Stock insuffisant")

            # ✅ Notifie le vendeur qu'il doit préparer une livraison
            try:
                from apps.notifications.service import NotificationService
                NotificationService.notify_seller_new_order(self, is_guest=True)
                logger.info(
                    f"Vendeur notifié pour la commande guest {self.order_number} "
                    f"(produit physique)"
                )
            except Exception as e:
                logger.error(
                    f"Erreur notification vendeur pour commande guest {self.order_number}: {e}"
                )

    def _credit_seller_wallet(self):
        """Crédite le wallet avec la commission dynamique du produit — anti-doublon."""
        from apps.dashboard.models import OrganizerWallet, WalletTransaction

        # ✅ Anti-doublon : ne crédite jamais deux fois la même commande
        already_credited = WalletTransaction.objects.filter(
            reference=self.order_number
        ).exists()
        if already_credited:
            logger.info(
                f"Transaction déjà créditée pour la commande guest {self.order_number}, ignorée"
            )
            return

        commission_rate = float(self.product.commission_rate) / 100
        net_amount = int(round(float(self.subtotal) * (1 - commission_rate)))

        wallet, _ = OrganizerWallet.objects.get_or_create(
            organizer=self.product.seller
        )
        wallet.credit(
            amount=net_amount,
            description=f"Vente boutique — {self.product.name}",
            reference=self.order_number,
        )
        logger.info(
            f"Wallet crédité pour la commande guest {self.order_number}: "
            f"{net_amount} FCFA"
        )

    def _generate_download_links(self):
        """
        Génère de NOUVEAUX liens à chaque achat, sans jamais réutiliser
        ou invalider les liens d'achats précédents.
        """
        for _ in range(self.quantity):
            GuestDownloadLink.objects.create(
                order=self,
                product=self.product,
                max_downloads=self.product.download_limit,
                expires_at=timezone.now() + timezone.timedelta(
                    hours=self.product.download_expiry_hours
                )
            )
        logger.info(
            f"{self.quantity} lien(s) de téléchargement généré(s) pour "
            f"la commande guest {self.order_number}"
        )

    def cancel(self):
        """
        Annule la commande et restaure le stock si nécessaire.
        """
        if self.status in [self.Status.PENDING, self.Status.PAID]:
            self.status = self.Status.CANCELLED
            self.save()
            
            # Restaurer le stock si commande était payée et produit physique
            if self.product.is_physical and self.status == self.Status.PAID:
                self.product.stock += self.quantity
                self.product.save(update_fields=['stock'])
                logger.info(
                    f"Stock restauré pour la commande guest annulée {self.order_number}"
                )

    def refund(self):
        """
        Rembourse la commande.
        """
        if self.status == self.Status.PAID:
            self.status = self.Status.REFUNDED
            self.save()
            
            # Restaurer le stock si produit physique
            if self.product.is_physical:
                self.product.stock += self.quantity
                self.product.save(update_fields=['stock'])
                logger.info(
                    f"Stock restauré pour la commande guest remboursée {self.order_number}"
                )

    def has_previously_purchased(self):
        """
        Vérifie si le client a déjà acheté ce produit auparavant.
        """
        return GuestProductOrder.objects.filter(
            email=self.email,
            product=self.product,
            status=self.Status.PAID
        ).exists()


class GuestDownloadLink(models.Model):
    """
    Lien de téléchargement pour acheteur sans compte — indépendant par commande.
    """
    token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    order = models.ForeignKey(
        GuestProductOrder,
        on_delete=models.CASCADE,
        related_name='download_links',
        verbose_name=_('commande')
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='guest_download_links',
        verbose_name=_('produit')
    )
    download_count = models.PositiveIntegerField(
        _('téléchargements effectués'),
        default=0
    )
    max_downloads = models.PositiveIntegerField(
        _('limite de téléchargements'),
        default=3
    )
    expires_at = models.DateTimeField(
        _('expire le')
    )
    created_at = models.DateTimeField(
        _('créé le'),
        auto_now_add=True
    )

    class Meta:
        verbose_name = _('lien téléchargement invité')
        verbose_name_plural = _('liens téléchargement invités')

    def __str__(self):
        return f"Lien {self.token} — {self.product.name}"

    @property
    def is_expired(self):
        """Vérifie si le lien a expiré."""
        return timezone.now() > self.expires_at

    @property
    def is_exhausted(self):
        """Vérifie si le nombre max de téléchargements est atteint."""
        return self.download_count >= self.max_downloads

    @property
    def is_valid(self):
        """Vérifie si le lien est toujours valide."""
        return not self.is_expired and not self.is_exhausted

    @property
    def downloads_remaining(self):
        """Nombre de téléchargements restants."""
        return max(0, self.max_downloads - self.download_count)