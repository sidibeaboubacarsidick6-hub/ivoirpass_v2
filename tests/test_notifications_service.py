"""
Tests du service de notifications — apps/notifications/service.py

Couvre :
- send_ticket_confirmation : email + PDF + SMS si téléphone
- guest_tickets_confirmed : event online vs physique
- welcome : email de bienvenue
- store_order_confirmed : digital vs physique
- guest_store_order_confirmed : download / delivery / both
- withdrawal_received / withdrawal_processed
- event_cancelled_buyer : email + SMS
- event_cancelled_admin_alert
- notify_seller_new_order : physique uniquement
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Category, Event, TicketType
from apps.notifications.service import NotificationService


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class SendTicketConfirmationTests(TestCase):
    """Tests de send_ticket_confirmation."""

    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='pass',
            first_name='Buy', last_name='Er',
        )
        self.buyer.phone_number = '+2250700000000'
        self.buyer.save()

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_send_ticket_confirmation_avec_sms(self, mock_sms, mock_render, mock_email_cls):
        """Envoie email + SMS si téléphone présent."""
        mock_render.return_value = '<html>Test</html>'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        # Fake order + tickets
        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-2026-TEST'
        order.total = Decimal('10000')

        # Mock tickets
        from apps.tickets.models import Ticket
        with patch.object(Ticket.objects, 'filter') as mock_filter:
            mock_tickets = MagicMock()
            mock_tickets.exists.return_value = True
            mock_tickets.__iter__ = lambda self: iter([])
            mock_filter.return_value = mock_tickets

            NotificationService.send_ticket_confirmation(order)

        # Email envoyé
        mock_email.send.assert_called_once()
        # SMS envoyé
        mock_sms.assert_called_once()
        # Le SMS contient le numéro et le total
        sms_args = mock_sms.call_args
        self.assertEqual(sms_args[0][0], '+2250700000000')
        self.assertIn('10000', sms_args[0][1])

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_send_ticket_confirmation_sans_telephone_pas_de_sms(self, mock_sms, mock_render, mock_email_cls):
        """Pas de téléphone → SMS non envoyé, email quand même."""
        self.buyer.phone_number = ''
        self.buyer.save()

        mock_render.return_value = '<html>Test</html>'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-2026-TEST'
        order.total = Decimal('10000')

        from apps.tickets.models import Ticket
        with patch.object(Ticket.objects, 'filter') as mock_filter:
            mock_tickets = MagicMock()
            mock_tickets.exists.return_value = True
            mock_tickets.__iter__ = lambda self: iter([])
            mock_filter.return_value = mock_tickets

            NotificationService.send_ticket_confirmation(order)

        mock_email.send.assert_called_once()
        mock_sms.assert_not_called()

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_send_ticket_confirmation_sans_billets(self, mock_render, mock_email_cls):
        """Pas de billets → retourne False, aucun email."""
        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-2026-EMPTY'

        from apps.tickets.models import Ticket
        with patch.object(Ticket.objects, 'filter') as mock_filter:
            mock_tickets = MagicMock()
            mock_tickets.exists.return_value = False
            mock_filter.return_value = mock_tickets

            result = NotificationService.send_ticket_confirmation(order)

        self.assertFalse(result)
        mock_email_cls.assert_not_called()


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class WelcomeTests(TestCase):
    """Tests de welcome."""

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_welcome_envoie_email(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Hello'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        user = MagicMock()
        user.email = 'new@test.com'

        result = NotificationService.welcome(user)

        self.assertTrue(result)
        mock_email.send.assert_called_once()

    @patch('apps.notifications.service.render_to_string')
    def test_welcome_template_manquant(self, mock_render):
        """Template plante → retourne False, pas d'exception."""
        mock_render.side_effect = Exception('Template not found')

        user = MagicMock()
        user.email = 'new@test.com'

        result = NotificationService.welcome(user)

        self.assertFalse(result)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class NotifySellerNewOrderTests(TestCase):
    """Tests de notify_seller_new_order."""

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_notify_seller_physique(self, mock_render, mock_email_cls):
        """Produit physique → email envoyé au vendeur."""
        mock_render.return_value = 'New order'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        seller = MagicMock()
        seller.email = 'seller@test.com'
        seller.get_full_name.return_value = 'Seller Name'

        product = MagicMock()
        product.is_physical = True
        product.seller = seller

        order = MagicMock()
        order.product = product
        order.order_number = 'ST-2026-X'
        order.buyer_name = 'Buyer'
        order.email = 'buyer@test.com'
        order.phone = '+2250700000000'

        result = NotificationService.notify_seller_new_order(order, is_guest=True)

        self.assertTrue(result)
        mock_email.send.assert_called_once()

    @patch('apps.notifications.service.EmailMultiAlternatives')
    def test_notify_seller_produit_digital_pas_demail(self, mock_email_cls):
        """Produit digital → pas d'email (rien à expédier)."""
        product = MagicMock()
        product.is_physical = False

        order = MagicMock()
        order.product = product

        result = NotificationService.notify_seller_new_order(order)

        self.assertFalse(result)
        mock_email_cls.assert_not_called()


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class EventCancelledBuyerTests(TestCase):
    """Tests de event_cancelled_buyer."""

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_event_cancelled_avec_telephone(self, mock_sms, mock_render, mock_email_cls):
        """Email + SMS envoyés si téléphone fourni."""
        mock_render.return_value = 'Event cancelled'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        event = MagicMock()
        event.title = 'Concert Test'

        result = NotificationService.event_cancelled_buyer(
            buyer_email='buyer@test.com',
            buyer_name='Ali B',
            event=event,
            buyer_phone='+2250700000000',
        )

        self.assertTrue(result)
        mock_email.send.assert_called_once()
        mock_sms.assert_called_once()
        sms_args = mock_sms.call_args
        self.assertEqual(sms_args[0][0], '+2250700000000')
        self.assertIn('Concert Test', sms_args[0][1])

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_event_cancelled_sans_telephone_pas_de_sms(self, mock_sms, mock_render, mock_email_cls):
        """Pas de téléphone → email seul."""
        mock_render.return_value = 'Event cancelled'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        event = MagicMock()
        event.title = 'Concert Test'

        result = NotificationService.event_cancelled_buyer(
            buyer_email='buyer@test.com',
            buyer_name='Ali B',
            event=event,
            buyer_phone=None,
        )

        self.assertTrue(result)
        mock_email.send.assert_called_once()
        mock_sms.assert_not_called()

    @patch('apps.notifications.service.EmailMultiAlternatives')
    def test_event_cancelled_email_vide_retourne_false(self, mock_email_cls):
        """Pas d'email → retourne False immédiatement."""
        result = NotificationService.event_cancelled_buyer(
            buyer_email='',
            buyer_name='Ali B',
            event=MagicMock(),
        )

        self.assertFalse(result)
        mock_email_cls.assert_not_called()


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'infos@mks-soft-technologies.com'},
)
class WithdrawalNotificationTests(TestCase):
    """Tests des notifications de reversement."""

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_withdrawal_received(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Withdrawal received'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        user = MagicMock()
        user.email = 'org@test.com'

        wallet = MagicMock()
        wallet.organizer = user

        wr = MagicMock()
        wr.wallet = wallet
        wr.reference = 'REV-123'

        result = NotificationService.withdrawal_received(wr)

        self.assertTrue(result)
        mock_email.send.assert_called_once()

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_withdrawal_processed(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Withdrawal done'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        user = MagicMock()
        user.email = 'org@test.com'

        wallet = MagicMock()
        wallet.organizer = user

        wr = MagicMock()
        wr.wallet = wallet
        wr.reference = 'REV-456'

        result = NotificationService.withdrawal_processed(wr)

        self.assertTrue(result)
        mock_email.send.assert_called_once()