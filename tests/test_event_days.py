"""
Tests Vague 4 Session A — Modèle EventDay + M2M TicketType.event_days.
"""
from datetime import date, time

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, EventDay, TicketType
from apps.scanner.models import ScanLog


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='O', last_name='G',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_event(organizer, slug=None):
    import uuid as _uuid
    if slug is None:
        slug = f'event-{_uuid.uuid4().hex[:8]}'
    now = timezone.now()
    return Event.objects.create(
        title='Festival Test',
        slug=slug,
        description='d',
        short_description='Festival test',
        organizer=organizer,
        start_date=now + timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=32),
        status=Event.Status.PUBLISHED,
    )


class EventDayModelTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)

    def test_creation_event_day_simple(self):
        day = EventDay.objects.create(
            event=self.event,
            date=date(2026, 12, 15),
        )
        self.assertEqual(day.event, self.event)
        self.assertEqual(day.date, date(2026, 12, 15))
        self.assertEqual(day.name, '')
        self.assertEqual(day.order, 0)

    def test_creation_avec_nom_personnalise(self):
        day = EventDay.objects.create(
            event=self.event,
            date=date(2026, 12, 15),
            name="Soirée d'ouverture",
            doors_open=time(19, 0),
            order=1,
        )
        self.assertEqual(day.name, "Soirée d'ouverture")
        self.assertEqual(day.doors_open, time(19, 0))

    def test_display_name_utilise_nom_si_present(self):
        day = EventDay.objects.create(
            event=self.event, date=date(2026, 12, 15),
            name="Finale",
        )
        self.assertEqual(day.display_name, "Finale")

    def test_display_name_utilise_date_si_pas_de_nom(self):
        day = EventDay.objects.create(
            event=self.event, date=date(2026, 12, 15),
        )
        # Mardi 15 Décembre 2026 en français → contient le mois
        self.assertIn('15', day.display_name)
        self.assertIn('2026', day.display_name)

    def test_unicite_event_et_date(self):
        EventDay.objects.create(
            event=self.event, date=date(2026, 12, 15),
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            EventDay.objects.create(
                event=self.event, date=date(2026, 12, 15),
            )

    def test_ordre_par_order_puis_date(self):
        EventDay.objects.create(
            event=self.event, date=date(2026, 12, 17), order=3,
        )
        EventDay.objects.create(
            event=self.event, date=date(2026, 12, 15), order=1,
        )
        EventDay.objects.create(
            event=self.event, date=date(2026, 12, 16), order=2,
        )
        days = list(self.event.event_days.all())
        self.assertEqual(days[0].date, date(2026, 12, 15))
        self.assertEqual(days[1].date, date(2026, 12, 16))
        self.assertEqual(days[2].date, date(2026, 12, 17))


class TicketTypeEventDaysM2MTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)
        self.day1 = EventDay.objects.create(
            event=self.event, date=date(2026, 12, 15), order=1,
        )
        self.day2 = EventDay.objects.create(
            event=self.event, date=date(2026, 12, 16), order=2,
        )
        self.day3 = EventDay.objects.create(
            event=self.event, date=date(2026, 12, 17), order=3,
        )

    def test_ticket_type_legacy_sans_event_days(self):
        """Un TicketType sans event_days = comportement legacy."""
        tt = TicketType.objects.create(
            event=self.event, name='Standard', price=5000,
        )
        self.assertEqual(tt.event_days.count(), 0)

    def test_ticket_type_1_jour(self):
        """Un TicketType lié à 1 EventDay = billet 1 jour."""
        tt = TicketType.objects.create(
            event=self.event, name='Vendredi soir', price=10000,
        )
        tt.event_days.add(self.day1)
        self.assertEqual(tt.event_days.count(), 1)
        self.assertIn(self.day1, tt.event_days.all())

    def test_ticket_type_pass_multi_jours(self):
        """Un TicketType lié à N EventDays = pass multi-jours."""
        tt = TicketType.objects.create(
            event=self.event, name='Pass 3 jours', price=24000,
        )
        tt.event_days.set([self.day1, self.day2, self.day3])
        self.assertEqual(tt.event_days.count(), 3)

    def test_ticket_types_du_jour(self):
        """Depuis un EventDay, on retrouve ses TicketTypes."""
        tt_jour = TicketType.objects.create(
            event=self.event, name='Vendredi soir', price=10000,
        )
        tt_jour.event_days.add(self.day1)

        tt_pass = TicketType.objects.create(
            event=self.event, name='Pass 3 jours', price=24000,
        )
        tt_pass.event_days.set([self.day1, self.day2, self.day3])

        jour1_types = self.day1.ticket_types.all()
        self.assertEqual(jour1_types.count(), 2)

        jour2_types = self.day2.ticket_types.all()
        self.assertEqual(jour2_types.count(), 1)
        self.assertEqual(jour2_types.first().name, 'Pass 3 jours')


class ScanLogEventDayTests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.event = _make_event(self.org)
        self.day = EventDay.objects.create(
            event=self.event, date=date(2026, 12, 15),
        )

    def test_scanlog_accepte_event_day_null(self):
        """ScanLog peut avoir event_day=None (compat legacy)."""
        from apps.scanner.models import ScanSession
        session = ScanSession.objects.create(
            agent=self.org, event=self.event,
        )
        log = ScanLog.objects.create(
            session=session,
            qr_data_received='test',
            result=ScanLog.Result.VALID,
            event_day=None,
        )
        self.assertIsNone(log.event_day)

    def test_scanlog_avec_event_day(self):
        from apps.scanner.models import ScanSession
        session = ScanSession.objects.create(
            agent=self.org, event=self.event,
        )
        log = ScanLog.objects.create(
            session=session,
            qr_data_received='test',
            result=ScanLog.Result.VALID,
            event_day=self.day,
        )
        self.assertEqual(log.event_day, self.day)
        self.assertIn(log, self.day.scan_logs.all())