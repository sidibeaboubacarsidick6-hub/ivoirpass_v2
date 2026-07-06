"""
Tests pour les vues de billetterie
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch

from apps.accounts.models import CustomUser
from apps.events.models import Event, TicketType
from apps.tickets.models import Order, OrderItem, Ticket


class TicketsViewsTest(TestCase):
    """Tests pour les vues de billetterie"""
    
    def setUp(self):
        self.client = Client()
        
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
            title='Concert Test',
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
    
    # ============================================================
    # TESTS POUR get_cart / save_cart
    # ============================================================
    
    def test_get_cart_empty(self):
        """Test que get_cart retourne un dict vide par défaut"""
        response = self.client.get(reverse('tickets:cart'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('cart', response.context)
        self.assertEqual(response.context['cart'], {})
    
    def test_add_to_cart_requires_login(self):
        """Test que l'ajout au panier nécessite une connexion"""
        response = self.client.get(
            reverse('tickets:add_to_cart', args=[self.ticket_type.id])
        )
        self.assertEqual(response.status_code, 302)  # Redirection login
    
    # ============================================================
    # TESTS POUR add_to_cart
    # ============================================================
    
    def test_add_to_cart_success(self):
        """Test d'ajout au panier"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('tickets:add_to_cart', args=[self.ticket_type.id]),
            {'quantity': 2}
        )
        self.assertEqual(response.status_code, 302)  # Redirection
        
        # Vérifier que le panier a été mis à jour
        session = self.client.session
        cart = session.get('cart', {})
        self.assertIn(str(self.ticket_type.id), cart)
        self.assertEqual(cart[str(self.ticket_type.id)], 2)
    
    def test_add_to_cart_invalid_ticket_type(self):
        """Test d'ajout avec un type de ticket invalide"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('tickets:add_to_cart', args=[999])
        )
        self.assertEqual(response.status_code, 404)
    
    def test_add_to_cart_quantity_zero(self):
        """Test d'ajout avec quantité zéro"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('tickets:add_to_cart', args=[self.ticket_type.id]),
            {'quantity': 0}
        )
        self.assertEqual(response.status_code, 302)
        
        # Le panier ne devrait pas contenir ce ticket
        session = self.client.session
        cart = session.get('cart', {})
        self.assertNotIn(str(self.ticket_type.id), cart)
    
    # ============================================================
    # TESTS POUR remove_from_cart
    # ============================================================
    
    def test_remove_from_cart_success(self):
        """Test de retrait du panier"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        # D'abord ajouter
        session = self.client.session
        session['cart'] = {str(self.ticket_type.id): 2}
        session.save()
        
        # Puis retirer
        response = self.client.post(
            reverse('tickets:remove_from_cart', args=[self.ticket_type.id])
        )
        self.assertEqual(response.status_code, 302)
        
        # Vérifier que le panier est vide
        session = self.client.session
        cart = session.get('cart', {})
        self.assertNotIn(str(self.ticket_type.id), cart)
    
    def test_remove_from_cart_invalid_item(self):
        """Test de retrait d'un item inexistant"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('tickets:remove_from_cart', args=[999])
        )
        self.assertEqual(response.status_code, 404)
    
    # ============================================================
    # TESTS POUR checkout
    # ============================================================
    
    def test_checkout_requires_login(self):
        """Test que le checkout nécessite une connexion"""
        response = self.client.get(reverse('tickets:checkout'))
        self.assertEqual(response.status_code, 302)
    
    def test_checkout_empty_cart(self):
        """Test de checkout avec panier vide"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('tickets:checkout'))
        self.assertEqual(response.status_code, 302)  # Redirection vers panier
    
    def test_checkout_with_cart(self):
        """Test de checkout avec panier non vide"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        # Ajouter au panier
        session = self.client.session
        session['cart'] = {str(self.ticket_type.id): 2}
        session.save()
        
        response = self.client.get(reverse('tickets:checkout'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tickets/checkout.html')
    
    def test_checkout_free_event(self):
        """Test de checkout pour un événement gratuit"""
        # Créer un ticket gratuit
        free_ticket = TicketType.objects.create(
            event=self.event,
            name='Gratuit',
            price=0,
            quantity=10,
            max_per_order=5,
        )
        
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        session = self.client.session
        session['cart'] = {str(free_ticket.id): 1}
        session.save()
        
        response = self.client.post(reverse('tickets:checkout'))
        self.assertEqual(response.status_code, 302)  # Redirection vers confirmation
    
    def test_checkout_exceeds_quantity(self):
        """Test de checkout avec quantité > disponible"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        # Ajouter plus que disponible
        session = self.client.session
        session['cart'] = {str(self.ticket_type.id): 100}
        session.save()
        
        response = self.client.post(reverse('tickets:checkout'))
        self.assertEqual(response.status_code, 200)  # Affiche erreur
        self.assertContains(response, 'quantité')
    
    # ============================================================
    # TESTS POUR order_confirmation
    # ============================================================
    
    def test_order_confirmation_requires_login(self):
        """Test que la confirmation nécessite une connexion"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PENDING,
        )
        response = self.client.get(
            reverse('tickets:confirmation', args=[order.order_number])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_order_confirmation_success(self):
        """Test de confirmation de commande"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PENDING,
        )
        OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            quantity=2,
            unit_price=15000,
        )
        
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('tickets:confirmation', args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tickets/confirmation.html')
        self.assertEqual(response.context['order'], order)
    
    def test_order_confirmation_wrong_user(self):
        """Test de confirmation par un autre utilisateur"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PENDING,
        )
        
        other_user = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('tickets:confirmation', args=[order.order_number])
        )
        self.assertIn(response.status_code, [302, 403, 404])
    
    # ============================================================
    # TESTS POUR my_tickets
    # ============================================================
    
    def test_my_tickets_requires_login(self):
        """Test que la liste des billets nécessite une connexion"""
        response = self.client.get(reverse('tickets:my_tickets'))
        self.assertEqual(response.status_code, 302)
    
    def test_my_tickets_success(self):
        """Test de la liste des billets"""
        # Créer une commande payée avec des tickets
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PAID,
        )
        order_item = OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            quantity=2,
            unit_price=15000,
        )
        # Créer les tickets
        for _ in range(2):
            Ticket.objects.create(order_item=order_item)
        
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('tickets:my_tickets'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tickets/my_tickets.html')
        self.assertIn('tickets', response.context)
        self.assertEqual(response.context['tickets'].count(), 2)
    
    def test_my_tickets_empty(self):
        """Test de la liste des billets vide"""
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('tickets:my_tickets'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tickets'].count(), 0)
    
    # ============================================================
    # TESTS POUR ticket_detail
    # ============================================================
    
    def test_ticket_detail_requires_login(self):
        """Test que le détail d'un billet nécessite une connexion"""
        ticket = Ticket.objects.create(
            order_item=OrderItem.objects.create(
                order=Order.objects.create(
                    buyer=self.participant,
                    subtotal=15000,
                    total=15000,
                    status=Order.Status.PAID,
                ),
                ticket_type=self.ticket_type,
                quantity=1,
                unit_price=15000,
            )
        )
        response = self.client.get(
            reverse('tickets:ticket_detail', args=[ticket.ticket_number])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_ticket_detail_success(self):
        """Test du détail d'un billet"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PAID,
        )
        order_item = OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            quantity=1,
            unit_price=15000,
        )
        ticket = Ticket.objects.create(
            order_item=order_item,
            status=Ticket.Status.VALID,
        )
        
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('tickets:ticket_detail', args=[ticket.ticket_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tickets/ticket_detail.html')
        self.assertEqual(response.context['ticket'], ticket)
    
    def test_ticket_detail_wrong_user(self):
        """Test du détail d'un billet par un autre utilisateur"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PAID,
        )
        order_item = OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            quantity=1,
            unit_price=15000,
        )
        ticket = Ticket.objects.create(
            order_item=order_item,
            status=Ticket.Status.VALID,
        )
        
        other_user = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('tickets:ticket_detail', args=[ticket.ticket_number])
        )
        self.assertIn(response.status_code, [302, 403, 404])
    
    # ============================================================
    # TESTS POUR download_ticket_pdf
    # ============================================================
    
    def test_download_ticket_pdf_requires_login(self):
        """Test que le téléchargement PDF nécessite une connexion"""
        ticket = Ticket.objects.create(
            order_item=OrderItem.objects.create(
                order=Order.objects.create(
                    buyer=self.participant,
                    subtotal=15000,
                    total=15000,
                    status=Order.Status.PAID,
                ),
                ticket_type=self.ticket_type,
                quantity=1,
                unit_price=15000,
            )
        )
        response = self.client.get(
            reverse('tickets:download_pdf', args=[ticket.ticket_number])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_download_ticket_pdf_success(self):
        """Test de téléchargement PDF"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PAID,
        )
        order_item = OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            quantity=1,
            unit_price=15000,
        )
        ticket = Ticket.objects.create(
            order_item=order_item,
            status=Ticket.Status.VALID,
        )
        
        self.client.login(email='part@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('tickets:download_pdf', args=[ticket.ticket_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
    
    def test_download_ticket_pdf_wrong_user(self):
        """Test de téléchargement PDF par un autre utilisateur"""
        order = Order.objects.create(
            buyer=self.participant,
            subtotal=15000,
            total=15000,
            status=Order.Status.PAID,
        )
        order_item = OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            quantity=1,
            unit_price=15000,
        )
        ticket = Ticket.objects.create(
            order_item=order_item,
            status=Ticket.Status.VALID,
        )
        
        other_user = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('tickets:download_pdf', args=[ticket.ticket_number])
        )
        self.assertIn(response.status_code, [302, 403, 404])

