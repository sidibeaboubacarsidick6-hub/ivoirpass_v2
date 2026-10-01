"""
Tests Vague 4 Session D — Scanner multi-jours (2026-10-01).

Vérifie :
- Legacy (billet sans event_days) : 1 scan définitif → non-régression
- Multi-jours : 1 scan par jour, le billet reste VALID
- Billet scanné hors de ses jours : refus
- Double scan même jour : refus
- Scan jour suivant : accepté
- ScanLog enregistre bien event_day + guest_ticket
"""
import json
import uuid as _uuid
from datetime import date, datetime, timedelta
from unittest.mock import patch
import apps.scanner.api.views as scanner_api_views

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, EventDay, TicketType
from apps.tickets.models import GuestOrder, GuestOrderItem, GuestTicket
from apps.scanner.models import ScanLog


# ── Dates de référence ──────────────────────────────────────────
D1 = date(2026, 12, 15)   # Jour 1
D2 = date(2026, 12, 16)   # Jour 2
D3 = date(2026, 12, 17)   # Jour 3
D4 = date(2026, 12, 18)   # Hors plage


def _mock_now_on(d):
    """Retourne un datetime aware fixe à 20h sur la date donnée."""
    return timezone.make_aware(
        datetime.combine(d, datetime.min.time().replace(hour=20))
    )


# ── Helpers ─────────────────────────────────────────────────────
def _make_agent(email='agent@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass',
        first_name='Agent', last_name='Test',
    )
    u.role = CustomUser.Role.SCANNER
    u.save()
    return u


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass',
        first_name='Orga', last_name='Test',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_event(organizer, days=None):
    now = timezone.now()
    event = Event.objects.create(
        title='Festival Test',
        slug=f'fest-{_uuid.uuid4().hex[:8]}',
        description='d',
        short_description='0700000000',
        organizer=organizer,
        start_date=now + timedelta(days=30),
        end_date=now + timedelta(days=32),
        status=Event.Status.PUBLISHED,
    )
    if days:
        for i, d in enumerate(days, start=1):
            EventDay.objects.create(event=event, date=d, order=i)
    return event


def _make_guest_ticket(ticket_type, email='buyer@test.com'):
    order = GuestOrder.objects.create(
        first_name='Jean', last_name='Dupont', email=email,
        subtotal=ticket_type.price, total=ticket_type.price,
        status=GuestOrder.Status.PAID, paid_at=timezone.now(),
    )
    item = GuestOrderItem.objects.create(
        order=order, ticket_type=ticket_type,
        quantity=1, unit_price=ticket_type.price,
        subtotal=ticket_type.price,
    )
    item.generate_tickets()
    return GuestTicket.objects.filter(order_item=item).first()


# ── Tests legacy (non-régression) ───────────────────────────────
class ScannerLegacyTests(TestCase):
    """Billet sans event_days : 1 scan définitif (comportement actuel)."""

    def setUp(self):
        self.organizer = _make_organizer()
        self.agent = _make_agent()
        self.event = _make_event(self.organizer)   # pas d'EventDays
        self.event.scanner_agents.add(self.agent)
        self.ticket_type = TicketType.objects.create(
            event=self.event, name='Standard', price=5000,
        )
        self.ticket = _make_guest_ticket(self.ticket_type)
        self.client.force_login(self.agent)

    def _scan(self):
        return self.client.post(
            '/api/scanner/scan/',
            data=json.dumps({
                'qr_data': self.ticket.qr_code_data,
                'event_id': self.event.id,
            }),
            content_type='application/json',
        )

    def test_premier_scan_valide_puis_second_refuse(self):
        # 1er scan : OK
        resp = self._scan()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['result'], 'valid')
        self.assertIsNone(data['ticket_info'].get('event_day'))

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, 'used')

        # 2e scan : refusé
        resp2 = self._scan()
        data2 = resp2.json()
        self.assertEqual(data2['result'], 'already_used')
        self.assertIn('Déjà utilisé', data2['message'])


# ── Tests multi-jours ────────────────────────────────────────────
class ScannerMultiDayTests(TestCase):
    """Billet multi-jours : 1 scan par jour, billet reste VALID."""

    def setUp(self):
        self.organizer = _make_organizer()
        self.agent = _make_agent()
        self.event = _make_event(self.organizer, days=[D1, D2, D3])
        self.event.scanner_agents.add(self.agent)
        self.days = list(self.event.event_days.order_by('date'))

        # Pass 3 jours
        self.tt_pass = TicketType.objects.create(
            event=self.event, name='Pass 3 jours', price=25000,
        )
        self.tt_pass.event_days.set(self.days)
        self.ticket_pass = _make_guest_ticket(self.tt_pass)

        # Billet jour 1 uniquement
        self.tt_j1 = TicketType.objects.create(
            event=self.event, name='Jour 1', price=10000,
        )
        self.tt_j1.event_days.add(self.days[0])
        self.ticket_j1 = _make_guest_ticket(self.tt_j1, email='j1@test.com')

        self.client.force_login(self.agent)

    def _scan(self, ticket, on_date):
        """
        Patche UNIQUEMENT timezone dans le module scanner (pas globalement),
        pour ne pas casser la vérification de session Django.
        """
        with patch.object(scanner_api_views, 'timezone') as mock_tz:
            mock_tz.now.return_value = _mock_now_on(on_date)
            mock_tz.timedelta = timezone.timedelta   # au cas où
            return self.client.post(
                '/api/scanner/scan/',
                data=json.dumps({
                    'qr_data': ticket.qr_code_data,
                    'event_id': self.event.id,
                }),
                content_type='application/json',
            )

    def test_pass_scan_jour_1_valide(self):
        resp = self._scan(self.ticket_pass, D1)
        self.assertEqual(resp.json()['result'], 'valid')
        self.assertEqual(
            resp.json()['ticket_info']['event_day'],
            self.days[0].display_name,
        )
        # Le billet reste VALID (pas USED)
        self.ticket_pass.refresh_from_db()
        self.assertEqual(self.ticket_pass.status, 'valid')

    def test_pass_double_scan_meme_jour_refuse(self):
        self._scan(self.ticket_pass, D1)
        resp = self._scan(self.ticket_pass, D1)
        self.assertEqual(resp.json()['result'], 'already_used')
        self.assertIn("Déjà scanné aujourd'hui", resp.json()['message'])

    def test_pass_scan_jour_2_valide_apres_jour_1(self):
        self._scan(self.ticket_pass, D1)
        resp = self._scan(self.ticket_pass, D2)
        self.assertEqual(resp.json()['result'], 'valid')
        self.ticket_pass.refresh_from_db()
        self.assertEqual(self.ticket_pass.status, 'valid')

    def test_pass_scan_hors_jours_refuse(self):
        resp = self._scan(self.ticket_pass, D4)
        self.assertEqual(resp.json()['result'], 'wrong_event')
        self.assertIn("pas valide aujourd'hui", resp.json()['message'])

    def test_billet_j1_scanne_jour_2_refuse(self):
        resp = self._scan(self.ticket_j1, D2)
        self.assertEqual(resp.json()['result'], 'wrong_event')
        self.assertIn("pas valide aujourd'hui", resp.json()['message'])

    def test_scanlog_enregistre_event_day_et_guest_ticket(self):
        self._scan(self.ticket_pass, D1)
        log = ScanLog.objects.filter(
            event_day=self.days[0],
            result=ScanLog.Result.VALID,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.guest_ticket, self.ticket_pass)