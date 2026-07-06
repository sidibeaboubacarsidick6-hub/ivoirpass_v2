"""
Tests pour le service PayDunya
"""
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

import requests

from apps.accounts.models import CustomUser
from apps.events.models import Event, TicketType
from apps.tickets.models import Order, OrderItem, Ticket
from apps.payments.paydunya import PayDunyaService


class PayDunyaServiceTest(TestCase):
    """Tests pour PayDunyaService"""
    
    def setUp(self):
        """Configuration des données de test"""
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
            title='Concert Test PayDunya',
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
    
    # ============================================================
    # TESTS POUR create_invoice
    # ============================================================
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_success(self, mock_post):
        """Test de création de facture réussie"""
        # Simuler une réponse PayDunya réussie
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'response_text': 'https://paydunya.com/sandbox-checkout/invoice/test_abc123',
            'token': 'test_abc123'
        }
        mock_post.return_value = mock_response
        
        result = PayDunyaService.create_invoice(self.order)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['payment_url'], 'https://paydunya.com/sandbox-checkout/invoice/test_abc123')
        self.assertEqual(result['token'], 'test_abc123')
        self.assertIsNone(result['error'])
        
        # Vérifier que la requête a été faite avec les bons paramètres
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['timeout'], 30)
        self.assertIn('json', kwargs)
        self.assertEqual(kwargs['json']['invoice']['total_amount'], '15000')
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_paydunya_error(self, mock_post):
        """Test de création avec erreur PayDunya"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '99',
            'response_text': 'Erreur de paiement'
        }
        mock_post.return_value = mock_response
        
        result = PayDunyaService.create_invoice(self.order)
        
        self.assertFalse(result['success'])
        self.assertIsNone(result.get('payment_url'))
        self.assertEqual(result['error'], 'Erreur de paiement')
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_timeout(self, mock_post):
        """Test de création avec timeout"""
        mock_post.side_effect = requests.exceptions.Timeout()
        
        result = PayDunyaService.create_invoice(self.order)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Délai de connexion dépassé. Veuillez réessayer.')
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_connection_error(self, mock_post):
        """Test de création avec erreur de connexion"""
        mock_post.side_effect = requests.exceptions.ConnectionError()
        
        result = PayDunyaService.create_invoice(self.order)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Impossible de se connecter à PayDunya.')
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_generic_exception(self, mock_post):
        """Test de création avec une exception générique"""
        mock_post.side_effect = Exception('Erreur inattendue')
        
        result = PayDunyaService.create_invoice(self.order)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Erreur inattendue')
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_builds_correct_payload(self, mock_post):
        """Test que le payload construit est correct"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'response_text': 'https://paydunya.com/invoice/test',
            'token': 'test_token'
        }
        mock_post.return_value = mock_response
        
        PayDunyaService.create_invoice(self.order)
        
        # Récupérer le payload envoyé
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        
        # Vérifier la structure du payload
        self.assertEqual(payload['store']['name'], 'IvoirPass')
        self.assertEqual(payload['invoice']['total_amount'], '15000')
        self.assertEqual(payload['invoice']['description'], f'Commande IvoirPass {self.order.order_number}')
        self.assertEqual(payload['custom_data']['order_number'], self.order.order_number)
        self.assertEqual(payload['custom_data']['buyer_email'], self.participant.email)
        
        # Vérifier les URLs
        self.assertIn(self.order.order_number, payload['actions']['return_url'])
        self.assertIn(self.order.order_number, payload['actions']['cancel_url'])
        self.assertIn('/paiements/webhook/', payload['actions']['callback_url'])
    
    @patch('apps.payments.paydunya.requests.post')
    def test_create_invoice_with_multiple_items(self, mock_post):
        """Test de création avec plusieurs items"""
        # Ajouter un deuxième item
        OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            quantity=2,
            unit_price=10000,
        )
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'response_text': 'https://paydunya.com/invoice/test',
            'token': 'test_token'
        }
        mock_post.return_value = mock_response
        
        PayDunyaService.create_invoice(self.order)
        
        # Vérifier que les deux items sont dans le payload
        args, kwargs = mock_post.call_args
        payload = kwargs['json']
        
        items = payload['invoice']['items']
        self.assertEqual(len(items), 2)
    
    # ============================================================
    # TESTS POUR verify_payment
    # ============================================================
    
    @patch('apps.payments.paydunya.requests.get')
    def test_verify_payment_success_completed(self, mock_get):
        """Test de vérification réussie - paiement complété"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'invoice': {
                'status': 'completed',
                'token': 'test_token'
            }
        }
        mock_get.return_value = mock_response
        
        result = PayDunyaService.verify_payment('test_token')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'completed')
        self.assertIsNone(result['error'])
    
    @patch('apps.payments.paydunya.requests.get')
    def test_verify_payment_success_pending(self, mock_get):
        """Test de vérification - paiement en attente"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'invoice': {
                'status': 'pending',
                'token': 'test_token'
            }
        }
        mock_get.return_value = mock_response
        
        result = PayDunyaService.verify_payment('test_token')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'pending')
    
    @patch('apps.payments.paydunya.requests.get')
    def test_verify_payment_success_cancelled(self, mock_get):
        """Test de vérification - paiement annulé"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'invoice': {
                'status': 'cancelled',
                'token': 'test_token'
            }
        }
        mock_get.return_value = mock_response
        
        result = PayDunyaService.verify_payment('test_token')
        
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'cancelled')
    
    @patch('apps.payments.paydunya.requests.get')
    def test_verify_payment_error(self, mock_get):
        """Test de vérification avec erreur PayDunya"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '99',
            'response_text': 'Token invalide'
        }
        mock_get.return_value = mock_response
        
        result = PayDunyaService.verify_payment('invalid_token')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'Token invalide')
    
    @patch('apps.payments.paydunya.requests.get')
    def test_verify_payment_exception(self, mock_get):
        """Test de vérification avec exception"""
        mock_get.side_effect = Exception('Erreur de connexion')
        
        result = PayDunyaService.verify_payment('test_token')
        
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'Erreur de connexion')
    
    @patch('apps.payments.paydunya.requests.get')
    def test_verify_payment_calls_correct_url(self, mock_get):
        """Test que l'URL de vérification est correcte"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'invoice': {'status': 'completed'}
        }
        mock_get.return_value = mock_response
        
        PayDunyaService.verify_payment('test_token_123')
        
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertIn('test_token_123', args[0])
        self.assertEqual(kwargs['timeout'], 30)
        self.assertIsNotNone(kwargs.get('headers'))
    
    # ============================================================
    # TESTS D'INTÉGRATION (avec les vues)
    # ============================================================
    
    @patch('apps.payments.paydunya.requests.post')
    def test_full_payment_flow_with_paydunya(self, mock_post):
        """Test du flux complet avec PayDunya mocké"""
        # Simuler une réponse PayDunya
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'response_code': '00',
            'response_text': 'https://paydunya.com/invoice/test_flow',
            'token': 'test_flow_123'
        }
        mock_post.return_value = mock_response
        
        # Créer une facture
        result = PayDunyaService.create_invoice(self.order)
        
        self.assertTrue(result['success'])
        self.assertIsNotNone(result['payment_url'])
        self.assertIsNotNone(result['token'])
        
        # Simuler la vérification
        with patch('apps.payments.paydunya.requests.get') as mock_get:
            mock_get_response = MagicMock()
            mock_get_response.json.return_value = {
                'response_code': '00',
                'invoice': {'status': 'completed'}
            }
            mock_get.return_value = mock_get_response
            
            verify_result = PayDunyaService.verify_payment(result['token'])
            self.assertTrue(verify_result['success'])
            self.assertEqual(verify_result['status'], 'completed')

