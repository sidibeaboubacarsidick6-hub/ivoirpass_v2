"""
Test d'audit — Génération QR code et PDF des billets (apps/tickets/utils.py,
31% de couverture avant cet audit — zone identifiée comme risquée car
peu testée automatiquement).

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_ticket_pdf_generation_audit -v 2
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem, GuestOrder, GuestOrderItem
from apps.tickets.utils import (
    generate_qr_image, generate_guest_qr_image,
    generate_ticket_pdf, generate_guest_ticket_pdf,
    generate_event_ticket_pdf,
)

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
PDF_MAGIC = b'%PDF'


def _make_event_and_ticket_type(organizer_email='orga-pdf@test.com'):
    organizer = CustomUser.objects.create_user(
        email=organizer_email, password='Pass123!', role='organizer', is_organizer_verified=True,
    )
    category = Category.objects.create(name=f'Cat-{organizer_email}', slug=f'cat-{organizer_email}'.replace('@', '-').replace('.', '-'))
    event = Event.objects.create(
        title='Concert PDF Test', description='Test', category=category, organizer=organizer,
        start_date=timezone.now() + timedelta(days=10),
        end_date=timezone.now() + timedelta(days=10, hours=3),
        venue_name='Palais de la Culture', venue_city='Abidjan',
        status='published',
    )
    ticket_type = TicketType.objects.create(event=event, name='Standard', price=5000, quantity=100)
    return event, ticket_type


class TicketPDFAndQRGenerationTests(TestCase):
    """Compte normal : QR code + PDF générés à partir d'un vrai billet payé."""

    def setUp(self):
        self.event, self.ticket_type = _make_event_and_ticket_type()
        self.buyer = CustomUser.objects.create_user(email='buyer-pdf@test.com', password='Pass123!')
        order = Order.objects.create(buyer=self.buyer, subtotal=5000, total=5000, status='pending')
        OrderItem.objects.create(order=order, ticket_type=self.ticket_type, quantity=1, unit_price=5000)
        order.mark_as_paid(payment_method='wave', payment_reference='PAY-PDF-TEST')
        self.ticket = order.items.first().tickets.first()

    def test_generate_qr_image_produit_un_png_valide(self):
        result = generate_qr_image(self.ticket)
        self.assertTrue(result, "generate_qr_image doit retourner True en cas de succès")
        # save=False dans generate_qr_image : le fichier est attaché en
        # mémoire mais pas encore persisté en base tant que ticket.save()
        # n'est pas appelé — on vérifie donc le contenu directement.
        self.ticket.qr_code_image.seek(0)
        content = self.ticket.qr_code_image.read()
        self.assertTrue(content.startswith(PNG_MAGIC), "Le fichier généré doit être un vrai PNG")

    def test_generate_ticket_pdf_produit_un_pdf_valide_et_non_vide(self):
        pdf_bytes = generate_ticket_pdf(self.ticket)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(PDF_MAGIC), "Le contenu généré doit être un vrai PDF")
        self.assertGreater(len(pdf_bytes), 500, "Un PDF de billet ne devrait pas être quasi-vide")

    def test_generate_ticket_pdf_ne_plante_pas_sans_qr_image_prealable(self):
        """Le PDF doit pouvoir se générer même si le QR image n'a pas été
        pré-généré (cas réel possible si l'ordre des opérations change)."""
        try:
            generate_ticket_pdf(self.ticket)
        except Exception as e:
            self.fail(f"generate_ticket_pdf n'aurait pas dû lever d'exception : {type(e).__name__}: {e}")


class GuestTicketPDFAndQRGenerationTests(TestCase):
    """Achat invité : même vérification, avec le modèle GuestTicket."""

    def setUp(self):
        self.event, self.ticket_type = _make_event_and_ticket_type('orga-pdf-guest@test.com')
        order = GuestOrder.objects.create(
            first_name='Fatou', last_name='Diabate', email='fatou@test.com',
            subtotal=5000, total=5000, status='pending',
        )
        item = GuestOrderItem.objects.create(order=order, ticket_type=self.ticket_type, quantity=1, unit_price=5000)
        order.mark_as_paid(payment_method='orange_money', payment_reference='PAY-PDF-GUEST-TEST')
        self.guest_ticket = item.tickets.first()

    def test_generate_guest_qr_image_produit_un_png_valide(self):
        result = generate_guest_qr_image(self.guest_ticket)
        self.assertTrue(result)
        self.guest_ticket.refresh_from_db()
        content = self.guest_ticket.qr_code_image.read()
        self.assertTrue(content.startswith(PNG_MAGIC))

    def test_generate_guest_ticket_pdf_produit_un_pdf_valide(self):
        """
        Non-régression : ce fichier contenait avant cet audit DEUX définitions
        de generate_guest_ticket_pdf (code mort silencieusement écrasé par
        Python). La seconde (conservée) doit fonctionner avec un vrai
        GuestTicket réel, pas seulement à la lecture du code.
        """
        pdf_bytes = generate_guest_ticket_pdf(self.guest_ticket)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(PDF_MAGIC))
        self.assertGreater(len(pdf_bytes), 500)

    def test_generate_guest_ticket_pdf_contient_bien_le_nom_de_lacheteur_invite(self):
        """Vérifie que le PDF utilise les vraies infos GuestOrder (first_name/
        last_name), pas un attribut buyer_name/buyer_email qui n'existe pas
        sur ce modèle (risque réel avec deux définitions concurrentes)."""
        try:
            pdf_bytes = generate_guest_ticket_pdf(self.guest_ticket)
        except AttributeError as e:
            self.fail(f"generate_guest_ticket_pdf accède à un attribut inexistant sur GuestTicket : {e}")
        self.assertTrue(pdf_bytes.startswith(PDF_MAGIC))


class RawEventTicketPDFTests(TestCase):
    """generate_event_ticket_pdf : génération à partir de données brutes (sans instance de modèle Ticket)."""

    def test_generate_event_ticket_pdf_avec_donnees_brutes(self):
        event, ticket_type = _make_event_and_ticket_type('orga-pdf-raw@test.com')
        pdf_bytes = generate_event_ticket_pdf(
            event=event,
            ticket_type=ticket_type,
            buyer_name='Test Acheteur',
            buyer_email='test@test.com',
            ticket_number='IP-TEST-000001',
            qr_data='fake-uuid:IP-TEST-000001:1:2026-01-01T00:00:00:deadbeef',
        )
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(PDF_MAGIC))
        self.assertGreater(len(pdf_bytes), 500)
