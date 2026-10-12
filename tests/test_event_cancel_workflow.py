"""
Tests du workflow d'annulation en 2 étapes (Cas inhabituel n°2).

Couvre :
- get_cancellation_impact() : calcul de l'écart
- event_delete : redirection vers la page de confirmation si wallet insuffisant
- event_cancel_confirm : création de la demande CANCEL_PENDING
- Actions admin approve_cancellation et refuse_cancellation
"""
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.events.models import Category, Event, TicketType
from apps.events.services import get_cancellation_impact
from apps.dashboard.models import OrganizerWallet
from apps.tickets.models import GuestOrder, GuestOrderItem, GuestTicket
from apps.dashboard.models import AuditLog

from django.contrib.admin.sites import AdminSite
from apps.events.admin import EventAdmin


User = get_user_model()


def _make_event_with_sales(email_suffix='a'):
    """Crée un organisateur + événement + 1 vente payée."""
    organizer = User.objects.create_user(
        email=f'org-{email_suffix}@test.com',
        password='test1234',
        first_name='Org', last_name='A',
        role=User.Role.ORGANIZER,
    )
    cat, _ = Category.objects.get_or_create(
        slug=f'cat-{email_suffix}',
        defaults={'name': f'Cat {email_suffix}'},
    )
    now = timezone.now()
    event = Event.objects.create(
        title=f'Event {email_suffix}',
        slug=f'event-{email_suffix}',
        description='d',
        short_description='0700000000',
        category=cat,
        organizer=organizer,
        start_date=now + timedelta(days=30),
        end_date=now + timedelta(days=31),
        status=Event.Status.PUBLISHED,
        commission_rate=Decimal('8.00'),
    )
    tt = TicketType.objects.create(
        event=event, name='Standard',
        price=Decimal('5000'), quantity=100,
    )

    # Créer une commande guest payée
    order = GuestOrder.objects.create(
        first_name='Buy', last_name='Er',
        email=f'buyer-{email_suffix}@test.com',
        phone='+22507000000',
        total=Decimal('5000'),
        status=GuestOrder.Status.PAID,
        payment_method='paydunya',
        paid_at=now,
    )
    item = GuestOrderItem.objects.create(
        order=order, ticket_type=tt,
        quantity=1, unit_price=Decimal('5000'),
    )
    GuestTicket.objects.create(
        order_item=item,
        ticket_number=f'TK-{email_suffix}-1',
        status=GuestTicket.Status.VALID,
    )
    # Recharger pour avoir tickets_sold à jour
    event.refresh_from_db()
    # Forcer manuellement tickets_sold (normalement mis à jour par signal)
    event.tickets_sold = 1
    event.save(update_fields=['tickets_sold'])

    return organizer, event


class CancellationImpactTests(TestCase):
    """Tests du helper get_cancellation_impact."""

    def test_impact_sans_wallet(self):
        """Sans wallet créé → needs_confirmation = False."""
        _, event = _make_event_with_sales('nw')
        impact = get_cancellation_impact(event)
        self.assertEqual(impact['sales_count'], 1)
        self.assertEqual(impact['sales_total'], Decimal('5000'))
        self.assertEqual(impact['wallet_available'], Decimal('0'))
        self.assertFalse(impact['needs_confirmation'])

    def test_impact_wallet_suffisant(self):
        """Wallet >= ventes → needs_confirmation = False."""
        organizer, event = _make_event_with_sales('ws')
        OrganizerWallet.objects.create(
            organizer=organizer,
            balance_events_available=Decimal('10000'),
        )
        impact = get_cancellation_impact(event)
        self.assertEqual(impact['wallet_available'], Decimal('10000'))
        self.assertEqual(impact['shortfall'], Decimal('0'))
        self.assertFalse(impact['needs_confirmation'])

    def test_impact_wallet_insuffisant(self):
        """Wallet < ventes → needs_confirmation = True."""
        organizer, event = _make_event_with_sales('wi')
        OrganizerWallet.objects.create(
            organizer=organizer,
            balance_events_available=Decimal('1000'),
        )
        impact = get_cancellation_impact(event)
        self.assertEqual(impact['wallet_available'], Decimal('1000'))
        self.assertEqual(impact['shortfall'], Decimal('4000'))
        self.assertTrue(impact['needs_confirmation'])


class EventDeleteRedirectTests(TestCase):
    """Tests de la redirection event_delete → event_cancel_confirm."""

    def setUp(self):
        self.organizer, self.event = _make_event_with_sales('rd')
        self.client = Client()
        self.client.force_login(self.organizer)

    def test_redirection_si_wallet_insuffisant(self):
        """Wallet < ventes → redirection vers cancel_confirm."""
        OrganizerWallet.objects.create(
            organizer=self.organizer,
            balance_events_available=Decimal('100'),
        )
        response = self.client.post(
            reverse('events:delete', kwargs={'slug': self.event.slug}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('annuler-confirmer', response.url)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.PUBLISHED)

    def test_annulation_normale_si_wallet_ok(self):
        """Wallet >= ventes → annulation immédiate."""
        OrganizerWallet.objects.create(
            organizer=self.organizer,
            balance_events_available=Decimal('50000'),
        )
        with patch('apps.notifications.service.NotificationService'):
            response = self.client.post(
                reverse('events:delete', kwargs={'slug': self.event.slug}),
            )
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CANCELLED)


class EventCancelConfirmTests(TestCase):
    """Tests de la vue event_cancel_confirm."""

    def setUp(self):
        self.organizer, self.event = _make_event_with_sales('cc')
        OrganizerWallet.objects.create(
            organizer=self.organizer,
            balance_events_available=Decimal('100'),
        )
        self.client = Client()
        self.client.force_login(self.organizer)

    def test_get_affiche_page(self):
        """GET affiche la page de confirmation."""
        response = self.client.get(
            reverse('events:cancel_confirm', kwargs={'slug': self.event.slug}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Responsabilité financière')
        self.assertContains(response, 'Écart à rembourser')

    def test_post_sans_case_acceptee_rejette(self):
        """POST sans cocher la case → message d'erreur, pas de changement."""
        response = self.client.post(
            reverse('events:cancel_confirm', kwargs={'slug': self.event.slug}),
            data={'cancel_reason': 'Test'},
        )
        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.PUBLISHED)

    def test_post_avec_case_passe_en_cancel_pending(self):
        """POST avec case cochée → CANCEL_PENDING + notification admin."""
        with patch('apps.notifications.tasks.notify_admins_async'):
            response = self.client.post(
                reverse('events:cancel_confirm', kwargs={'slug': self.event.slug}),
                data={
                    'accept_responsibility': 'on',
                    'cancel_reason': 'Météo défavorable',
                },
            )
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CANCEL_PENDING)
        self.assertEqual(self.event.cancel_requested_by, self.organizer)
        self.assertIn('Météo', self.event.cancel_request_reason)
        self.assertIsNotNone(self.event.cancel_requested_at)


class AdminApproveRefuseTests(TestCase):
    """Tests des actions admin approve_cancellation / refuse_cancellation."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email='admin@test.com',
            password='admin1234',
        )
        self.organizer, self.event = _make_event_with_sales('aa')
        OrganizerWallet.objects.create(
            organizer=self.organizer,
            balance_events_available=Decimal('100'),
        )
        # Passer en CANCEL_PENDING directement
        self.event.status = Event.Status.CANCEL_PENDING
        self.event.cancel_requested_at = timezone.now()
        self.event.cancel_requested_by = self.organizer
        self.event.cancel_request_reason = 'Test'
        self.event.save()

    def _make_request(self):
        """Crée un faux request compatible avec les actions admin."""
        from django.test import RequestFactory
        request = RequestFactory().post('/admin/events/event/')
        request.user = self.admin
        from unittest.mock import MagicMock
        request._messages = MagicMock()  # supporte .add() sans planter # sera remplacé par le mock de message_user
        return request

    @patch.object(EventAdmin, 'message_user')
    @patch('apps.notifications.service.NotificationService.send_email')
    @patch('apps.notifications.service.NotificationService')
    def test_approve_annule_effectivement(
        self, mock_ns, mock_send_email, mock_message_user,
    ):
        """approve → annulation effective."""
        admin_obj = EventAdmin(Event, AdminSite())
        request = self._make_request()

        admin_obj.approve_cancellation(
            request, Event.objects.filter(pk=self.event.pk),
        )
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.CANCELLED)
        mock_message_user.assert_called()

    @patch.object(EventAdmin, 'message_user')
    @patch('apps.notifications.service.NotificationService.send_email')
    def test_refuse_remet_published(self, mock_send_email, mock_message_user):
        """refuse → retour en PUBLISHED + champs effacés."""
        admin_obj = EventAdmin(Event, AdminSite())
        request = self._make_request()

        admin_obj.refuse_cancellation(
            request, Event.objects.filter(pk=self.event.pk),
        )
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.Status.PUBLISHED)
        self.assertIsNone(self.event.cancel_requested_at)
        self.assertEqual(self.event.cancel_request_reason, '')
        mock_message_user.assert_called()