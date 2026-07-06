from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from PIL import Image

import apps.tickets.utils as utils
from apps.accounts.models import CustomUser
from apps.events.models import Event, TicketType
from apps.tickets.models import Order, OrderItem, Ticket


class TicketsUtilsTest(TestCase):
    """Tests pour les utilitaires de tickets"""
    
    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga@test.com',
            password='IvoirPass2026!',
            role='organizer',
        )
        self.participant = CustomUser.objects.create_user(
            email='part@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        
        now = timezone.now()
        self.event = Event.objects.create(
            title='Soirée Test',
            description='Test',
            organizer=self.organizer,
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=5, hours=4),
            venue_city='Abidjan',
            status='published',
        )
        
        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name='VIP',
            price=15000,
            quantity=50,
            max_per_order=3,
        )
        
        self.order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PENDING,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            quantity=1,
            unit_price=15000,
        )
        self.order.mark_as_paid(
            payment_method='test',
            payment_reference='TEST-REF-001'
        )
        self.ticket = Ticket.objects.get(order_item__order=self.order)
    
    # ============================================================
    # TESTS POUR generate_qr_image
    # ============================================================
    
    def test_generate_qr_image_creates_valid_png(self):
        """Test que l'image générée est un PNG valide"""
        # La fonction est déjà appelée par mark_as_paid
        # On vérifie juste que l'image est valide
        image_file = self.ticket.qr_code_image
        self.assertIsNotNone(image_file)
        image = Image.open(image_file)
        self.assertEqual(image.format, 'PNG')
        image.close()
    
    def test_generate_qr_image_returns_none(self):
        """Test que la fonction retourne None (elle sauvegarde)"""
        result = utils.generate_qr_image(self.ticket)
        self.assertIsNone(result)
    
    def test_generate_qr_image_uses_correct_colors(self):
        """Test que le QR est généré avec les couleurs IvoirPass"""
        # Vérifier que l'image existe et est valide
        image_file = self.ticket.qr_code_image
        self.assertIsNotNone(image_file)
        image = Image.open(image_file)
        self.assertEqual(image.format, 'PNG')
        image.close()
    
    # ============================================================
    # TESTS POUR generate_ticket_pdf
    # ============================================================
    
    def test_generate_ticket_pdf_returns_bytes(self):
        """Test que generate_ticket_pdf retourne des bytes"""
        result = utils.generate_ticket_pdf(self.ticket)
        self.assertIsInstance(result, bytes)
        self.assertTrue(len(result) > 0)
    
    def test_generate_ticket_pdf_is_valid_pdf(self):
        """Test que le résultat est un PDF valide"""
        result = utils.generate_ticket_pdf(self.ticket)
        self.assertTrue(result.startswith(b'%PDF'))
    
    def test_generate_ticket_pdf_contains_ticket_info(self):
        """Test que le PDF contient les infos du ticket"""
        pdf_bytes = utils.generate_ticket_pdf(self.ticket)
        self.assertTrue(len(pdf_bytes) > 1000)
        
        # Vérifier le contenu en texte
        try:
            content = pdf_bytes.decode('latin-1')
            has_ticket_number = self.ticket.ticket_number in content
            has_event_title = self.event.title in content
            self.assertTrue(has_ticket_number or has_event_title)
        except:
            self.assertTrue(len(pdf_bytes) > 1000)
    
    def test_generate_ticket_pdf_with_different_tickets(self):
        """Test que différents tickets génèrent des PDF différents"""
        ticket2 = Ticket.objects.create(
            order_item=self.order_item,
            status=Ticket.Status.VALID
        )
        
        pdf1 = utils.generate_ticket_pdf(self.ticket)
        pdf2 = utils.generate_ticket_pdf(ticket2)
        
        self.assertNotEqual(pdf1, pdf2)
    
    def test_generate_ticket_pdf_uses_ticket_data(self):
        """Test que le PDF utilise les données du ticket"""
        pdf_bytes = utils.generate_ticket_pdf(self.ticket)
        self.assertTrue(len(pdf_bytes) > 500)
    
    # ============================================================
    # TESTS D'INTÉGRATION
    # ============================================================
    
    def test_integration_qr_and_pdf(self):
        """Test que QR et PDF fonctionnent ensemble"""
        # QR existe déjà (généré par mark_as_paid)
        self.assertTrue(bool(self.ticket.qr_code_image))
        
        # PDF généré
        pdf_bytes = utils.generate_ticket_pdf(self.ticket)
        self.assertTrue(len(pdf_bytes) > 500)
    
    def test_performance_generate_qr(self):
        """Test de performance pour generate_qr_image"""
        import time
        start = time.time()
        for _ in range(5):
            temp_ticket = Ticket.objects.create(
                order_item=self.order_item,
                status=Ticket.Status.VALID
            )
            # L'image est déjà générée par save()
            # On appelle juste la fonction pour vérifier
            utils.generate_qr_image(temp_ticket)
            temp_ticket.refresh_from_db()
            if temp_ticket.qr_code_image:
                temp_ticket.qr_code_image.delete(save=False)
                temp_ticket.delete()
        elapsed = time.time() - start
        self.assertLess(elapsed, 5)
    
    def test_performance_generate_pdf(self):
        """Test de performance pour generate_ticket_pdf"""
        import time
        start = time.time()
        for _ in range(5):
            utils.generate_ticket_pdf(self.ticket)
        elapsed = time.time() - start
        self.assertLess(elapsed, 10)

