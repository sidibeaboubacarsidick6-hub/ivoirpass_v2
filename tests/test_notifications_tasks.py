"""
Tests des tâches Celery notifications — apps/notifications/tasks.py
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from celery.exceptions import Retry

from apps.accounts.models import CustomUser
from apps.notifications import tasks as notif_tasks
from apps.notifications.models import AdminNotification


class ReportFailureTests(TestCase):
    @patch('sentry_sdk.capture_message')
    def test_report_failure_sans_exc(self, mock_capture):
        notif_tasks._log_and_report('Test erreur')
        mock_capture.assert_called_once()

    @patch('sentry_sdk.capture_exception')
    def test_report_failure_avec_exc(self, mock_capture):
        try:
            raise ValueError('Boom')
        except ValueError as e:
            notif_tasks._log_and_report('Msg', exc=e)
        mock_capture.assert_called_once()

    @patch('builtins.__import__', side_effect=ImportError('No sentry'))
    def test_report_failure_sans_sentry(self, mock_import):
        try:
            notif_tasks._log_and_report('Test')
        except ImportError:
            self.fail('Ne doit pas propager ImportError')


@override_settings(DEFAULT_FROM_EMAIL='noreply@test.com')
class SendEmailAsyncTests(TestCase):
    @patch('apps.notifications.tasks.EmailMultiAlternatives')
    def test_send_email_succes(self, mock_email_cls):
        mock_email_cls.return_value = MagicMock()
        result = notif_tasks.send_email_async(
            subject='Test', html_body='<b>Hi</b>', text_body='Hi',
            recipient_list=['a@test.com'],
        )
        self.assertIn('Email sent', result)

    @patch('apps.notifications.tasks.EmailMultiAlternatives')
    def test_send_email_erreur_leve_retry(self, mock_email_cls):
        mock_email_cls.side_effect = Exception('SMTP down')
        with self.assertRaises((Retry, Exception)):
            notif_tasks.send_email_async(
                subject='X', html_body='', text_body='',
                recipient_list=['a@test.com'],
            )


class LogEmailResultTests(TestCase):
    @patch('apps.dashboard.services.log_action')
    def test_succes_log(self, mock_log):
        notif_tasks._log_email_result(
            action_success='email_sent',
            description_success='OK',
            description_failure='KO',
            obj=MagicMock(), success=True,
        )
        mock_log.assert_called_once()

    @patch('apps.dashboard.services.log_action')
    def test_echec_log(self, mock_log):
        notif_tasks._log_email_result(
            action_success=None, description_success=None,
            description_failure='KO',
            obj=MagicMock(), success=False, error=Exception('Boom'),
        )
        mock_log.assert_called_once()


@override_settings(DEFAULT_FROM_EMAIL='noreply@test.com')
class SendTicketEmailAsyncTests(TestCase):
    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email='b@test.com', password='pass',
        )

    def _make_order(self):
        from apps.tickets.models import Order
        from decimal import Decimal
        return Order.objects.create(
            buyer=self.buyer, subtotal=Decimal('1000'),
            total=Decimal('1000'), status=Order.Status.PAID,
        )

    def test_commande_inexistante_retourne_none(self):
        result = notif_tasks.send_ticket_email_async(
            '00000000-0000-0000-0000-000000000000'
        )
        self.assertIsNone(result)

    @patch('apps.notifications.service.NotificationService')
    def test_succes_appelle_service(self, mock_service):
        order = self._make_order()
        mock_service.ticket_confirmed.return_value = True

        result = notif_tasks.send_ticket_email_async(str(order.uuid))
        self.assertIn('Tickets sent', result)
        mock_service.ticket_confirmed.assert_called_once()

    @patch('apps.notifications.service.NotificationService')
    def test_erreur_leve_retry(self, mock_service):
        order = self._make_order()
        mock_service.ticket_confirmed.side_effect = Exception('BOOM')

        with self.assertRaises((Retry, Exception)):
            notif_tasks.send_ticket_email_async(str(order.uuid))


@override_settings(DEFAULT_FROM_EMAIL='noreply@test.com')
class SendGuestTicketEmailAsyncTests(TestCase):
    def _make_guest_order(self):
        from apps.tickets.models import GuestOrder
        from decimal import Decimal
        return GuestOrder.objects.create(
            first_name='A', last_name='B', email='g@test.com',
            subtotal=Decimal('1000'), total=Decimal('1000'),
            status=GuestOrder.Status.PAID,
        )

    def test_inexistant_retourne_none(self):
        result = notif_tasks.send_guest_ticket_email_async(
            '00000000-0000-0000-0000-000000000000'
        )
        self.assertIsNone(result)

    @patch('apps.notifications.service.NotificationService')
    def test_succes(self, mock_service):
        order = self._make_guest_order()
        mock_service.guest_tickets_confirmed.return_value = True

        result = notif_tasks.send_guest_ticket_email_async(str(order.uuid))
        self.assertIn('Guest tickets sent', result)

    @patch('apps.notifications.service.NotificationService')
    def test_erreur_retry(self, mock_service):
        order = self._make_guest_order()
        mock_service.guest_tickets_confirmed.side_effect = Exception('BOOM')
        with self.assertRaises((Retry, Exception)):
            notif_tasks.send_guest_ticket_email_async(str(order.uuid))


@override_settings(DEFAULT_FROM_EMAIL='noreply@test.com')
class GenerateQrCodesAsyncTests(TestCase):
    @patch('apps.tickets.utils.generate_qr_image')
    def test_qr_generes(self, mock_gen):
        result = notif_tasks.generate_qr_codes_async([])
        self.assertIn('QR codes generated for 0 tickets', result)

    @patch('apps.tickets.utils.generate_qr_image')
    def test_erreur_leve_retry(self, mock_gen):
        mock_gen.side_effect = Exception('QR fail')
        from apps.tickets.models import Ticket
        # On mock filter pour retourner un ticket
        with patch.object(Ticket.objects, 'filter') as mock_filter:
            t = MagicMock()
            t.qr_code_image = None
            mock_filter.return_value = [t]
            with self.assertRaises((Retry, Exception)):
                notif_tasks.generate_qr_codes_async(['uuid-1'])


@override_settings(DEFAULT_FROM_EMAIL='noreply@test.com')
class NotifyAdminsAsyncTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            email='admin@test.com', password='pass',
            role=CustomUser.Role.ADMIN, notify_email=True, is_active=True,
        )

    @patch('django.core.mail.send_mail')
    def test_notifie_admins(self, mock_send):
        notif_tasks.notify_admins_async(
            notification_type='fraud_alert',
            title='Alerte',
            message='Message',
            reference='REF-1',
        )

        # AdminNotification créée
        self.assertTrue(
            AdminNotification.objects.filter(reference='REF-1').exists()
        )
        mock_send.assert_called_once()

    @patch('django.core.mail.send_mail')
    def test_sans_admins_ne_plante_pas(self, mock_send):
        CustomUser.objects.all().update(notify_email=False)
        notif_tasks.notify_admins_async(
            notification_type='fraud_alert',
            title='Alerte', message='Msg',
        )
        mock_send.assert_not_called()

    @patch('django.core.mail.send_mail')
    def test_erreur_email_avalee(self, mock_send):
        mock_send.side_effect = Exception('SMTP down')
        # Ne doit pas lever
        notif_tasks.notify_admins_async(
            notification_type='fraud_alert',
            title='Alerte', message='Msg',
        )
        # AdminNotification créée malgré l'échec email
        self.assertTrue(AdminNotification.objects.exists())


@override_settings(DEFAULT_FROM_EMAIL='noreply@test.com')
class SendDownloadLinkEmailAsyncTests(TestCase):
    def test_product_order_inexistant(self):
        result = notif_tasks.send_download_link_email_async(
            '00000000-0000-0000-0000-000000000000'
        )
        self.assertIsNone(result)

    @patch('apps.store.utils.send_download_link_email')
    def test_succes(self, mock_send):
        from apps.store.models import ProductOrder, Product, ProductCategory
        from apps.accounts.models import CustomUser
        from decimal import Decimal

        seller = CustomUser.objects.create_user(email='s@test.com', password='p')
        buyer = CustomUser.objects.create_user(email='b@test.com', password='p')
        cat = ProductCategory.objects.create(name='Cat', slug='cat')
        product = Product.objects.create(
            name='P', description='d', seller=seller, category=cat,
            price=Decimal('1000'),
        )
        order = ProductOrder.objects.create(
            buyer=buyer, product=product, quantity=1,
            unit_price=Decimal('1000'), subtotal=Decimal('1000'),
            total=Decimal('1000'),
        )

        result = notif_tasks.send_download_link_email_async(str(order.uuid))
        self.assertIn('Download links sent', result)
        mock_send.assert_called_once()

    @patch('apps.store.utils.send_download_link_email')
    def test_erreur_retry(self, mock_send):
        from apps.store.models import ProductOrder, Product, ProductCategory
        from apps.accounts.models import CustomUser
        from decimal import Decimal

        seller = CustomUser.objects.create_user(email='s2@test.com', password='p')
        buyer = CustomUser.objects.create_user(email='b2@test.com', password='p')
        cat = ProductCategory.objects.create(name='Cat2', slug='cat2')
        product = Product.objects.create(
            name='P2', description='d', seller=seller, category=cat,
            price=Decimal('1000'),
        )
        order = ProductOrder.objects.create(
            buyer=buyer, product=product, quantity=1,
            unit_price=Decimal('1000'), subtotal=Decimal('1000'),
            total=Decimal('1000'),
        )
        mock_send.side_effect = Exception('BOOM')

        with self.assertRaises((Retry, Exception)):
            notif_tasks.send_download_link_email_async(str(order.uuid))