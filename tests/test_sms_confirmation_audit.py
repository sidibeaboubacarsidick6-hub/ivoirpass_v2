"""
Test d'audit — Le SMS de confirmation doit partir en plus de l'email
après un achat de billet réussi (Phase 5 du script MVP).

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_sms_confirmation_audit -v 2
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem
from apps.notifications.service import NotificationService


class SMSConfirmationTests(TestCase):

    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email='buyer-sms@test.com', password='Pass123!', phone_number='+2250700000000',
        )
        organizer = CustomUser.objects.create_user(
            email='orga-sms@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        category = Category.objects.create(name='Concert SMS', slug='concert-sms')
        event = Event.objects.create(
            title='Concert SMS Test', description='Test', category=category, organizer=organizer,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            status='published',
        )
        ticket_type = TicketType.objects.create(event=event, name='Standard', price=5000, quantity=100)
        self.order = Order.objects.create(buyer=self.buyer, subtotal=5000, total=5000, status='pending')
        OrderItem.objects.create(order=self.order, ticket_type=ticket_type, quantity=1, unit_price=5000)
        self.order.mark_as_paid(payment_method='wave', payment_reference='PAY-SMS-TEST')

    @patch('apps.notifications.sms.send_sms')
    def test_sms_envoye_apres_confirmation_billet(self, mock_send_sms):
        mock_send_sms.return_value = True
        NotificationService.ticket_confirmed(self.order)

        self.assertTrue(mock_send_sms.called, "send_sms n'a jamais été appelé après un achat confirmé")
        args, kwargs = mock_send_sms.call_args
        self.assertEqual(args[0], '+2250700000000')
        self.assertIn('5000', args[1])

    @patch('apps.notifications.sms.send_sms')
    def test_echec_sms_ne_bloque_pas_la_confirmation(self, mock_send_sms):
        """Si l'envoi SMS plante, l'email reste envoyé et la fonction ne casse pas."""
        mock_send_sms.side_effect = Exception("Erreur réseau SMS")
        result = NotificationService.ticket_confirmed(self.order)
        self.assertTrue(result, "Un échec SMS ne doit jamais faire échouer toute la confirmation")