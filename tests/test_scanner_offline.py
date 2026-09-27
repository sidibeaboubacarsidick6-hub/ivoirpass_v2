"""
IvoirPass V2 — Tests Chantier B : scanner PWA offline.

Couvre les endpoints serveur ajoutés en B-2 :
  - prepare_event_offline (pull billets)
  - sync_offline_scans (batch push avec idempotence)
"""
import json
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import (
    GuestOrder, GuestOrderItem, GuestTicket, Ticket,
    Order, OrderItem,
)


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='Org', last_name='T',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_agent(email='agent@test.com', managed_by=None):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='Ag', last_name='T',
    )
    u.role = CustomUser.Role.SCANNER
    if managed_by is not None:
        u.managed_by = managed_by
    u.save()
    return u


def _make_event(organizer, title='Event Test'):
    cat, _ = Category.objects.get_or_create(name='Test')
    return Event.objects.create(
        title=title, slug=title.lower().replace(' ', '-'),
        description='d', short_description='+225 07 00 00 00 00',
        category=cat, organizer=organizer,
        start_date=timezone.now(), end_date=timezone.now(),
        status=Event.Status.PUBLISHED,
        venue_name='X', venue_address='Y', venue_city='Z',
    )


def _make_guest_ticket(event, email='b@test.com', status='valid'):
    tt, _ = TicketType.objects.get_or_create(
        event=event, name='Std', defaults={'price': 5000, 'quantity': 100},
    )
    order = GuestOrder.objects.create(
        first_name='J', last_name='A', email=email,
        subtotal=5000, total=5000, status=GuestOrder.Status.PAID,
    )
    item = GuestOrderItem.objects.create(
        order=order, ticket_type=tt, quantity=1, unit_price=5000,
    )
    ticket = GuestTicket.objects.create(order_item=item)
    ticket.status = status
    ticket.save()
    return ticket


class PrepareOfflineTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.agent = _make_agent(managed_by=self.org)
        self.event = _make_event(self.org)
        self.event.scanner_agents.add(self.agent)
        self.ticket = _make_guest_ticket(self.event)
        self.client.force_login(self.agent)

    def _url(self):
        return reverse('scanner_api:prepare_offline', kwargs={'event_id': self.event.id})

    def test_renvoie_tous_les_billets_de_levenement(self):
        r = self.client.post(self._url())
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['event_id'], self.event.id)
        self.assertEqual(len(data['tickets']), 1)
        t = data['tickets'][0]
        self.assertEqual(t['ticket_number'], self.ticket.ticket_number)
        self.assertEqual(t['status'], 'valid')
        self.assertEqual(t['kind'], 'guest')

    def test_renvoie_401_si_non_authentifie(self):
        self.client.logout()
        r = self.client.post(self._url())
        self.assertEqual(r.status_code, 401)

    def test_renvoie_404_si_event_inexistant(self):
        r = self.client.post(
            reverse('scanner_api:prepare_offline', kwargs={'event_id': 99999})
        )
        self.assertEqual(r.status_code, 404)


class SyncOfflineTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.agent = _make_agent(managed_by=self.org)
        self.event = _make_event(self.org)
        self.event.scanner_agents.add(self.agent)
        self.ticket = _make_guest_ticket(self.event)
        self.client.force_login(self.agent)

    def _url(self):
        return reverse('scanner_api:sync_offline')

    def _post(self, scans):
        return self.client.post(
            self._url(),
            data=json.dumps({'event_id': self.event.id, 'scans': scans}),
            content_type='application/json',
        )

    def test_sync_valide_un_billet(self):
        r = self._post([{
            'client_uuid': '11111111-1111-4111-8111-111111111111',
            'qr_data': self.ticket.qr_code_data,
        }])
        self.assertEqual(r.status_code, 200)
        results = r.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['result'], 'valid')

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'used')

    def test_idempotence_meme_client_uuid(self):
        """Un client_uuid déjà traité renvoie le résultat original."""
        cu = '22222222-2222-4222-8222-222222222222'
        r1 = self._post([{'client_uuid': cu, 'qr_data': self.ticket.qr_code_data}])
        self.assertEqual(r1.json()['results'][0]['result'], 'valid')

        r2 = self._post([{'client_uuid': cu, 'qr_data': self.ticket.qr_code_data}])
        result2 = r2.json()['results'][0]
        self.assertTrue(result2.get('idempotent'))
        self.assertEqual(result2['result'], 'valid')

        # Un seul ScanLog créé
        from apps.scanner.models import ScanLog
        count = ScanLog.objects.filter(client_uuid=cu).count()
        self.assertEqual(count, 1)

    def test_limite_500_scans(self):
        scans = [
            {'client_uuid': f'33333333-3333-4333-8333-{i:012d}', 'qr_data': 'x'}
            for i in range(501)
        ]
        r = self._post(scans)
        self.assertEqual(r.status_code, 400)

    def test_sans_session_rejete(self):
        self.client.logout()
        r = self._post([])
        self.assertEqual(r.status_code, 401)