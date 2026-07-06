"""
IvoirPass V2 — Modèles de billetterie
"""
import uuid
import hmac
import hashlib
import random
import string
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class Order(models.Model):
    """
    Commande IvoirPass.
    Une commande peut contenir plusieurs tickets (OrderItem).
    """

    class Status(models.TextChoices):
        PENDING   = 'pending',   _('En attente de paiement')
        PAID      = 'paid',      _('Payée')
        CANCELLED = 'cancelled', _('Annulée')
        REFUNDED  = 'refunded',  _('Remboursée')

    # Identifiants
    order_number = models.CharField(
        _('numéro de commande'),
        max_length=20,
        unique=True,
        blank=True,
    )
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )

    # Acheteur
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name=_('acheteur')
    )

    # Montants
    subtotal = models.DecimalField(
        _('sous-total'),
        max_digits=12, decimal_places=0, default=0
    )
    commission = models.DecimalField(
        _('commission IvoirPass'),
        max_digits=12, decimal_places=0, default=0
    )
    total = models.DecimalField(
        _('total payé'),
        max_digits=12, decimal_places=0, default=0
    )

    # Statut
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Paiement
    payment_method = models.CharField(
        _('moyen de paiement'),
        max_length=50,
        blank=True,
        help_text="wave, orange_money, mtn_momo, card, cinetpay"
    )
    payment_reference = models.CharField(
        _('référence paiement'),
        max_length=200,
        blank=True
    )
    paid_at = models.DateTimeField(
        _('payée le'),
        null=True, blank=True
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('commande')
        verbose_name_plural = _('commandes')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['buyer', 'status']),
        ]

    def __str__(self):
        return f"Commande {self.order_number} — {self.buyer.email}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    def _generate_order_number(self):
        """Génère un numéro de commande unique : IP-2026-XXXXXX"""
        year = timezone.now().year
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"IP-{year}-{suffix}"

    def mark_as_paid(self, payment_method='', payment_reference=''):
        """Marque la commande comme payée et génère les tickets."""
        self.status = self.Status.PAID
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.paid_at = timezone.now()
        self.save()
        # Génère les tickets pour chaque ligne de commande
        for item in self.items.all():
            item.generate_tickets()

    def refund(self, reason=''):
        """
        Initie le remboursement de la commande.
        Invalide tous les tickets associés (statut → 'void').
        """
        self.status = self.Status.REFUNDED
        self.save()

        for item in self.items.all():
            item.tickets.update(status='void')

        return True

    @property
    def is_paid(self):
        return self.status == self.Status.PAID


class OrderItem(models.Model):
    """
    Ligne d'une commande — un type de ticket en une certaine quantité.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('commande')
    )
    ticket_type = models.ForeignKey(
        'events.TicketType',
        on_delete=models.CASCADE,
        related_name='order_items',
        verbose_name=_('type de ticket')
    )
    quantity = models.PositiveIntegerField(_('quantité'), default=1)
    unit_price = models.DecimalField(
        _('prix unitaire'),
        max_digits=10, decimal_places=0
    )
    subtotal = models.DecimalField(
        _('sous-total'),
        max_digits=12, decimal_places=0
    )

    class Meta:
        verbose_name = _('ligne de commande')
        verbose_name_plural = _('lignes de commande')

    def __str__(self):
        return f"{self.quantity}x {self.ticket_type.name} — {self.order.order_number}"

    def save(self, *args, **kwargs):
        self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def generate_tickets(self):
        """Génère un ticket individuel par unité achetée."""
        for _ in range(self.quantity):
            Ticket.objects.create(order_item=self)


class Ticket(models.Model):
    """
    Ticket individuel avec QR Code signé HMAC-SHA256.
    Un ticket = une entrée pour une personne.
    """

    class Status(models.TextChoices):
        VALID   = 'valid',   _('Valide')
        USED    = 'used',    _('Utilisé')
        EXPIRED = 'expired', _('Expiré')
        VOID    = 'void',    _('Annulé')

    # Identifiants
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    ticket_number = models.CharField(
        _('numéro de ticket'),
        max_length=30,
        unique=True,
        blank=True
    )
    qr_code_data = models.CharField(
        _('données QR Code'),
        max_length=500,
        blank=True,
        help_text="Chaîne signée HMAC encodée dans le QR Code"
    )
    qr_code_image = models.ImageField(
        _('image QR Code'),
        upload_to='tickets/qr/%Y/%m/',
        blank=True, null=True
    )

    # Liaison
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        related_name='tickets',
        verbose_name=_('ligne de commande')
    )

    # Statut
    status = models.CharField(
        _('statut'),
        max_length=20,
        choices=Status.choices,
        default=Status.VALID
    )

    # Scan
    scanned_at = models.DateTimeField(
        _('scanné le'),
        null=True, blank=True
    )
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scanned_tickets',
        verbose_name=_('scanné par')
    )

    # Dates
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('ticket')
        verbose_name_plural = _('tickets')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ticket_number']),
            models.Index(fields=['uuid']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Ticket {self.ticket_number} — {self.order_item.ticket_type.event.title}"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            self.ticket_number = self._generate_ticket_number()
        if not self.qr_code_data:
            self.qr_code_data = self._generate_qr_data()
        super().save(*args, **kwargs)
        # Génère l'image QR après la sauvegarde initiale
        if not self.qr_code_image:
            self._generate_qr_image()

    def _generate_ticket_number(self):
        """Génère un numéro de ticket : TK-XXXXXXXX"""
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return f"TK-{suffix}"

    def _generate_qr_data(self):
        """
        Génère la donnée signée HMAC-SHA256 du QR Code.
        Format : uuid:ticket_number:HMAC
        Impossible à falsifier sans la SECRET_KEY Django.
        """
        payload = f"{self.uuid}:{self.ticket_number}"
        signature = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]  # 16 premiers caractères suffisent
        return f"{payload}:{signature}"

    def _generate_qr_image(self):
        """Génère et sauvegarde l'image PNG du QR Code."""
        from .utils import generate_qr_image
        generate_qr_image(self)

    def verify_qr(self, qr_data):
        """Vérifie que les données QR sont authentiques."""
        return hmac.compare_digest(self.qr_code_data, qr_data)

    def mark_as_used(self, scanned_by=None):
        """Invalide le ticket après le premier scan."""
        self.status = self.Status.USED
        self.scanned_at = timezone.now()
        self.scanned_by = scanned_by
        self.save()

    @property
    def event(self):
        return self.order_item.ticket_type.event

    @property
    def ticket_type(self):
        return self.order_item.ticket_type

    @property
    def buyer(self):
        return self.order_item.order.buyer

    @property
    def is_valid(self):
        return self.status == self.Status.VALID


# ================================================================
# 🆕 MODÈLES POUR ACHAT SANS COMPTE (Guest)
# ================================================================

class GuestOrder(models.Model):
    """
    Commande passée sans compte utilisateur.
    L'acheteur reçoit son billet par email uniquement.
    """
    class Status(models.TextChoices):
        PENDING   = 'pending',   _('En attente')
        PAID      = 'paid',      _('Payée')
        CANCELLED = 'cancelled', _('Annulée')
        REFUNDED  = 'refunded',  _('Remboursée')

    order_number = models.CharField(
        _('numéro de commande'),
        max_length=20, unique=True, blank=True
    )
    uuid = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True
    )

    # Infos acheteur (sans compte)
    first_name = models.CharField(_('prénom'), max_length=100)
    last_name  = models.CharField(_('nom'),    max_length=100)
    email      = models.EmailField(_('email'))
    phone      = models.CharField(_('téléphone'), max_length=20, blank=True)

    # Montants
    subtotal   = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total      = models.DecimalField(max_digits=12, decimal_places=0, default=0)

    # Statut
    status            = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method    = models.CharField(max_length=50, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True)
    paid_at           = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('commande invité')
        verbose_name_plural = _('commandes invités')
        ordering = ['-created_at']

    def __str__(self):
        return f"Commande {self.order_number} — {self.email}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            year = timezone.now().year
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            self.order_number = f"IP-{year}-{suffix}"
        super().save(*args, **kwargs)

    def mark_as_paid(self, payment_method='', payment_reference=''):
        self.status = self.Status.PAID
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.paid_at = timezone.now()
        self.save()
        for item in self.guest_items.all():
            item.generate_tickets()

    @property
    def buyer_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class GuestOrderItem(models.Model):
    """Ligne de commande invité."""
    order = models.ForeignKey(
        GuestOrder,
        on_delete=models.CASCADE,
        related_name='guest_items'
    )
    ticket_type = models.ForeignKey(
        'events.TicketType',
        on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=0)

    class Meta:
        verbose_name = _('ligne de commande invité')
        verbose_name_plural = _('lignes de commande invités')

    def __str__(self):
        return f"{self.quantity}x {self.ticket_type.name} — {self.order.order_number}"

    def save(self, *args, **kwargs):
        self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def generate_tickets(self):
        for _ in range(self.quantity):
            GuestTicket.objects.create(order_item=self)


class GuestTicket(models.Model):
    """Ticket pour acheteur sans compte."""
    class Status(models.TextChoices):
        VALID   = 'valid',   _('Valide')
        USED    = 'used',    _('Utilisé')
        VOID    = 'void',    _('Annulé')

    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )
    ticket_number = models.CharField(
        max_length=30,
        unique=True,
        blank=True
    )
    qr_code_data = models.CharField(
        max_length=500,
        blank=True
    )
    qr_code_image = models.ImageField(
        upload_to='tickets/qr/%Y/%m/',
        blank=True,
        null=True
    )
    order_item = models.ForeignKey(
        GuestOrderItem,
        on_delete=models.CASCADE,
        related_name='tickets'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.VALID
    )
    scanned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('ticket invité')
        verbose_name_plural = _('tickets invités')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ticket_number']),
            models.Index(fields=['uuid']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Ticket invité {self.ticket_number} — {self.order_item.ticket_type.event.title}"

    def save(self, *args, **kwargs):
        if not self.ticket_number:
            self.ticket_number = 'TK-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not self.qr_code_data:
            self.qr_code_data = self._generate_qr_data()
        super().save(*args, **kwargs)
        if not self.qr_code_image:
            self._generate_qr_image()

    def _generate_qr_data(self):
        payload = f"{self.uuid}:{self.ticket_number}"
        signature = hmac.new(
            settings.SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        return f"{payload}:{signature}"

    def _generate_qr_image(self):
        from .utils import generate_guest_qr_image
        generate_guest_qr_image(self)

    def verify_qr(self, qr_data):
        return hmac.compare_digest(self.qr_code_data, qr_data)

    def mark_as_used(self):
        self.status = self.Status.USED
        self.scanned_at = timezone.now()
        self.save()

    @property
    def event(self):
        return self.order_item.ticket_type.event

    @property
    def ticket_type(self):
        return self.order_item.ticket_type

    @property
    def buyer_name(self):
        return self.order_item.order.buyer_name

    @property
    def buyer_email(self):
        return self.order_item.order.email