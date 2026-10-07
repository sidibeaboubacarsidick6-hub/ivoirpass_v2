"""
Tests complets du service de notifications — apps/notifications/service.py

Focus : email/SMS sur tous les parcours (billetterie, boutique, reversement,
annulation). Les templates sont mockés pour ne pas dépendre de leur présence.
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
class SendEmailTests(TestCase):
    @patch('django.core.mail.send_mail')
    def test_send_email_succes(self, mock_send):
        result = NotificationService.send_email(
            subject='Test', message='Corps',
            recipient_list=['a@test.com'],
        )
        self.assertTrue(result)
        mock_send.assert_called_once()

    @patch('django.core.mail.send_mail')
    def test_send_email_erreur(self, mock_send):
        mock_send.side_effect = Exception('SMTP down')
        result = NotificationService.send_email(
            subject='Test', message='Corps',
            recipient_list=['a@test.com'],
        )
        self.assertFalse(result)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class SendTicketConfirmationTests(TestCase):
    """Tests de send_ticket_confirmation (Order legacy)."""

    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='pass',
            phone_number='+2250700000000',
        )

    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.tickets.utils.generate_ticket_pdf')
    @patch('apps.tickets.models.Ticket.objects.filter')
    def test_email_avec_sms(self, mock_filter, mock_pdf, mock_render,
                            mock_email_cls, mock_sms):
        mock_render.return_value = 'Contenu'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email
        mock_pdf.return_value = b'%PDF'

        # Fake ticket
        ticket = MagicMock()
        ticket.ticket_number = 'TK-001'
        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        mock_qs.__iter__ = lambda self: iter([ticket])
        mock_filter.return_value = mock_qs

        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-2026-X'
        order.total = Decimal('10000')

        result = NotificationService.send_ticket_confirmation(order)

        self.assertTrue(result)
        mock_email.send.assert_called_once()
        mock_sms.assert_called_once()
        self.assertEqual(mock_sms.call_args[0][0], '+2250700000000')

    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.tickets.models.Ticket.objects.filter')
    def test_sans_telephone_pas_de_sms(self, mock_filter, mock_render,
                                       mock_email_cls, mock_sms):
        mock_render.return_value = 'Contenu'
        mock_email_cls.return_value = MagicMock()
        self.buyer.phone_number = ''
        self.buyer.save()

        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        mock_qs.__iter__ = lambda self: iter([])
        mock_filter.return_value = mock_qs

        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-2026-X'
        order.total = Decimal('10000')

        NotificationService.send_ticket_confirmation(order)

        mock_sms.assert_not_called()

    @patch('apps.tickets.models.Ticket.objects.filter')
    def test_sans_tickets_retourne_false(self, mock_filter):
        mock_qs = MagicMock()
        mock_qs.exists.return_value = False
        mock_filter.return_value = mock_qs

        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-EMPTY'

        result = NotificationService.send_ticket_confirmation(order)
        self.assertFalse(result)

    @patch('apps.notifications.service.render_to_string')
    @patch('apps.tickets.models.Ticket.objects.filter')
    def test_template_manquant_retourne_false(self, mock_filter, mock_render):
        mock_render.side_effect = Exception('TemplateMissing')
        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        mock_filter.return_value = mock_qs

        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'IP-2026-X'

        result = NotificationService.send_ticket_confirmation(order)
        self.assertFalse(result)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class GuestTicketsConfirmedTests(TestCase):
    """Tests de guest_tickets_confirmed avec de VRAIS objets Django."""

    def _setup_order_with_tickets(self, event_type='physical', num_tickets=1):
        """Crée un événement + tickets réels."""
        from apps.events.models import Category, Event, TicketType
        from apps.tickets.models import GuestOrder, GuestOrderItem, GuestTicket
        from decimal import Decimal
        from django.utils import timezone as tz

        # Organisateur
        org = CustomUser.objects.create_user(
            email=f'org-gtc-{event_type}@test.com', password='p',
            role=CustomUser.Role.ORGANIZER, is_organizer_verified=True,
        )
        cat = Category.objects.create(
            name=f'C-{event_type}', slug=f'c-gtc-{event_type}',
        )
        now = tz.now()
        event = Event.objects.create(
            title=f'E-{event_type}', slug=f'e-gtc-{event_type}',
            description='d', short_description='0700',
            category=cat, organizer=org,
            start_date=now + tz.timedelta(days=30),
            end_date=now + tz.timedelta(days=31),
            status='published', event_type=event_type,
            online_link='https://zoom.us/x' if event_type == 'online' else '',
        )
        tt = TicketType.objects.create(
            event=event, name='Std', price=Decimal('5000'), quantity=100,
        )
        order = GuestOrder.objects.create(
            first_name='Ali', last_name='B', email='guest-gtc@test.com',
            phone='+2250700000000',
            subtotal=Decimal('5000') * num_tickets,
            total=Decimal('5000') * num_tickets,
            status=GuestOrder.Status.PAID,
        )
        item = GuestOrderItem.objects.create(
            order=order, ticket_type=tt,
            quantity=num_tickets, unit_price=Decimal('5000'),
        )
        item.generate_tickets()
        return order

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    @patch('apps.tickets.utils.generate_guest_ticket_pdf')
    def test_physique_avec_pdf_et_sms(self, mock_pdf, mock_sms,
                                       mock_render, mock_email_cls):
        mock_render.return_value = 'Contenu'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email
        mock_pdf.return_value = b'%PDF'

        order = self._setup_order_with_tickets('physical')
        result = NotificationService.guest_tickets_confirmed(order)

        self.assertTrue(result)
        mock_email.send.assert_called_once()
        mock_sms.assert_called_once()

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_online_envoie_acces_lien(self, mock_sms, mock_render, mock_email_cls):
        mock_render.return_value = 'Contenu'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        order = self._setup_order_with_tickets('online')
        result = NotificationService.guest_tickets_confirmed(order)

        self.assertTrue(result)
        mock_sms.assert_called_once()
        sms_body = mock_sms.call_args[0][1]
        # Message pour événement online
        self.assertIn('lien de connexion', sms_body)

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_sans_tickets_retourne_false(self, mock_render, mock_email_cls):
        """Commande PAID sans aucun billet → False."""
        from apps.tickets.models import GuestOrder
        from decimal import Decimal

        order = GuestOrder.objects.create(
            first_name='Sans', last_name='Tickets', email='st@test.com',
            subtotal=Decimal('0'), total=Decimal('0'),
            status=GuestOrder.Status.PAID,
        )
        # Aucun item, aucun ticket créé

        result = NotificationService.guest_tickets_confirmed(order)
        self.assertFalse(result)

@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class WelcomeTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_welcome_succes(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Bienvenue'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        user = MagicMock()
        user.email = 'new@test.com'

        self.assertTrue(NotificationService.welcome(user))
        mock_email.send.assert_called_once()

    @patch('apps.notifications.service.render_to_string')
    def test_welcome_template_manquant(self, mock_render):
        mock_render.side_effect = Exception('Missing')
        user = MagicMock()
        user.email = 'new@test.com'
        self.assertFalse(NotificationService.welcome(user))


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class StoreOrderConfirmedTests(TestCase):
    """Tests de store_order_confirmed (ProductOrder legacy)."""

    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='pass',
            phone_number='+2250700000000',
        )

    def _make_order(self, is_digital):
        order = MagicMock()
        order.buyer = self.buyer
        order.order_number = 'ST-1'
        order.total = Decimal('5000')
        order.product.is_digital = is_digital
        return order

    @patch('apps.store.models.DownloadLink.objects.filter')
    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_digital_envoie_lien_et_sms(self, mock_render, mock_email_cls,
                                         mock_sms, mock_dl_filter):
        mock_render.return_value = 'Lien'
        mock_email_cls.return_value = MagicMock()
        mock_dl_filter.return_value = []

        order = self._make_order(is_digital=True)
        result = NotificationService.store_order_confirmed(order)

        self.assertTrue(result)
        mock_sms.assert_called_once()
        sms_body = mock_sms.call_args[0][1]
        self.assertIn('téléchargements', sms_body)

    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_physique_envoie_sms_preparation(self, mock_render, mock_email_cls,
                                             mock_sms):
        mock_render.return_value = 'Cmd'
        mock_email_cls.return_value = MagicMock()

        order = self._make_order(is_digital=False)
        NotificationService.store_order_confirmed(order)

        mock_sms.assert_called_once()
        sms_body = mock_sms.call_args[0][1]
        self.assertIn('préparation', sms_body)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class GuestStoreOrderConfirmedTests(TestCase):
    """Tests de guest_store_order_confirmed."""

    def setUp(self):
        self.order = MagicMock()
        self.order.email = 'guest@test.com'
        self.order.order_number = 'ST-G1'
        self.order.total = Decimal('5000')
        self.order.phone = '+2250700000000'
        self.order.buyer_name = 'Ali B'

    def _set_delivery(self, method):
        """Configure le delivery_method de la commande mockée."""
        self.order.DeliveryMethod = MagicMock()
        self.order.DeliveryMethod.DOWNLOAD = 'download'
        self.order.DeliveryMethod.DELIVERY = 'delivery'
        self.order.DeliveryMethod.BOTH = 'both'
        self.order.delivery_method = method

    @patch('apps.store.models.GuestDownloadLink.objects.filter')
    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_download_pur(self, mock_render, mock_email_cls,
                           mock_sms, mock_dl_filter):
        mock_render.return_value = 'Lien'
        mock_email_cls.return_value = MagicMock()
        mock_dl_filter.return_value = []

        self._set_delivery('download')
        result = NotificationService.guest_store_order_confirmed(self.order)

        self.assertTrue(result)
        sms_body = mock_sms.call_args[0][1]
        self.assertIn('téléchargements', sms_body)

    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_delivery_seul(self, mock_render, mock_email_cls, mock_sms):
        mock_render.return_value = 'Cmd'
        mock_email_cls.return_value = MagicMock()

        self._set_delivery('delivery')
        NotificationService.guest_store_order_confirmed(self.order)

        sms_body = mock_sms.call_args[0][1]
        self.assertIn('colis', sms_body)

    @patch('apps.store.models.GuestDownloadLink.objects.filter')
    @patch('apps.notifications.sms.send_sms')
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_both(self, mock_render, mock_email_cls, mock_sms, mock_dl_filter):
        mock_render.return_value = 'Cmd'
        mock_email_cls.return_value = MagicMock()
        mock_dl_filter.return_value = []

        self._set_delivery('both')
        NotificationService.guest_store_order_confirmed(self.order)

        sms_body = mock_sms.call_args[0][1]
        self.assertIn('Livraison en préparation', sms_body)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class WithdrawalNotificationTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_withdrawal_received(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Reçu'
        mock_email_cls.return_value = MagicMock()

        user = MagicMock(email='org@test.com')
        wr = MagicMock()
        wr.wallet.organizer = user
        wr.reference = 'REV-1'

        self.assertTrue(NotificationService.withdrawal_received(wr))

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_withdrawal_processed(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Fait'
        mock_email_cls.return_value = MagicMock()

        user = MagicMock(email='org@test.com')
        wr = MagicMock()
        wr.wallet.organizer = user
        wr.reference = 'REV-2'

        self.assertTrue(NotificationService.withdrawal_processed(wr))


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class EventReminderTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_reminder_envoie(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Rappel'
        mock_email_cls.return_value = MagicMock()

        user = MagicMock(email='u@test.com')
        event = MagicMock(title='Concert')
        ticket = MagicMock(buyer=user, event=event)

        self.assertTrue(NotificationService.event_reminder(ticket))


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class EventCancelledBuyerTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_avec_telephone_envoie_sms(self, mock_sms, mock_render, mock_email_cls):
        mock_render.return_value = 'Annulé'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        event = MagicMock(title='Concert XYZ')

        result = NotificationService.event_cancelled_buyer(
            buyer_email='b@test.com', buyer_name='Ali',
            event=event, buyer_phone='+2250700000000',
        )

        self.assertTrue(result)
        mock_sms.assert_called_once()
        self.assertIn('annulé', mock_sms.call_args[0][1].lower())

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_sans_telephone_pas_de_sms(self, mock_sms, mock_render, mock_email_cls):
        mock_render.return_value = 'Annulé'
        mock_email_cls.return_value = MagicMock()

        result = NotificationService.event_cancelled_buyer(
            buyer_email='b@test.com', buyer_name='Ali',
            event=MagicMock(title='X'), buyer_phone=None,
        )

        self.assertTrue(result)
        mock_sms.assert_not_called()

    def test_sans_email_retourne_false(self):
        result = NotificationService.event_cancelled_buyer(
            buyer_email='', buyer_name='Ali',
            event=MagicMock(),
        )
        self.assertFalse(result)

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    @patch('apps.notifications.sms.send_sms')
    def test_sms_erreur_ne_casse_pas_email(self, mock_sms, mock_render, mock_email_cls):
        mock_render.return_value = 'Annulé'
        mock_email_cls.return_value = MagicMock()
        mock_sms.side_effect = Exception('SMS down')

        result = NotificationService.event_cancelled_buyer(
            buyer_email='b@test.com', buyer_name='Ali',
            event=MagicMock(title='X'), buyer_phone='+2250700000000',
        )
        # Email parti, SMS raté — retourne True quand même
        self.assertTrue(result)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class EventCancelledAdminAlertTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_avec_admins_envoie(self, mock_render, mock_email_cls):
        CustomUser.objects.create_user(
            email='admin@test.com', password='pass',
            role=CustomUser.Role.ADMIN, notify_email=True, is_active=True,
        )
        mock_render.return_value = 'Alerte'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        event = MagicMock(title='X', organizer=MagicMock(), id=1)
        result = NotificationService.event_cancelled_admin_alert(
            event=event, orders_affected=3, tickets_voided=5,
            wallet_frozen=True, reason='Test',
        )

        self.assertTrue(result)
        mock_email.send.assert_called_once()

    @patch('apps.notifications.service.render_to_string')
    def test_sans_admins_retourne_false(self, mock_render):
        result = NotificationService.event_cancelled_admin_alert(
            event=MagicMock(title='X', organizer=MagicMock(), id=1),
            orders_affected=0, tickets_voided=0,
            wallet_frozen=False, reason='',
        )
        self.assertFalse(result)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class EventCancelledLegacyTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_legacy_guest_ticket(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Annulé'
        mock_email_cls.return_value = MagicMock()

        order = MagicMock(buyer_email='g@test.com')
        event = MagicMock(title='X')
        tt = MagicMock(event=event)
        oi = MagicMock(order=order, ticket_type=tt)
        ticket = MagicMock(order_item=oi)

        result = NotificationService.event_cancelled(ticket)
        self.assertTrue(result)


@override_settings(
    DEFAULT_FROM_EMAIL='noreply@ivoirpass.com',
    PAYDUNYA_BASE_URL='https://test.ivoirpass.com',
    IVOIRPASS={'CONTACT_EMAIL': 'support@test.com'},
)
class NotifySellerNewOrderTests(TestCase):
    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_physique_envoie_email(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Nouvelle cmd'
        mock_email = MagicMock()
        mock_email_cls.return_value = mock_email

        seller = MagicMock(email='seller@test.com')
        product = MagicMock(is_physical=True, seller=seller)
        order = MagicMock(product=product, order_number='ST-1',
                          buyer_name='Ali', email='a@test.com',
                          phone='+2250700000000')

        result = NotificationService.notify_seller_new_order(order, is_guest=True)

        self.assertTrue(result)
        mock_email.send.assert_called_once()

    def test_digital_retourne_false(self):
        product = MagicMock(is_physical=False)
        order = MagicMock(product=product)
        result = NotificationService.notify_seller_new_order(order)
        self.assertFalse(result)

    @patch('apps.notifications.service.EmailMultiAlternatives')
    @patch('apps.notifications.service.render_to_string')
    def test_account_order(self, mock_render, mock_email_cls):
        mock_render.return_value = 'Cmd'
        mock_email_cls.return_value = MagicMock()

        buyer = MagicMock()
        buyer.get_full_name.return_value = 'Buyer X'
        buyer.email = 'bx@test.com'
        buyer.phone_number = '+2250700000001'

        product = MagicMock(is_physical=True, seller=MagicMock(email='s@t.com'))
        order = MagicMock(product=product, order_number='ST-2', buyer=buyer)

        result = NotificationService.notify_seller_new_order(order, is_guest=False)
        self.assertTrue(result)