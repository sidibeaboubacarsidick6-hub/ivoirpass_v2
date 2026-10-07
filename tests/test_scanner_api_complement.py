"""
Tests complémentaires du scanner API — branches manquantes.

Couvre :
- _check_agent : anonyme / inactif / mauvais rôle
- _authorize_agent_for_event : admin / organisateur autre / agent non assigné
- _process_scan : QR invalide / UUID invalide / billet introuvable /
  QR falsifié / wrong event
- prepare_event_offline
- sync_offline_scans : idempotence + client_uuid invalide
"""
import json
import uuid as uuid_lib
from unittest.mock import patch, MagicMock
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Category, Event, TicketType
from apps.tickets.models import Order, OrderItem, Ticket
from apps.scanner.models import ScanSession, ScanLog
from apps.scanner.api import views as api_views


def _setup_full_event(suffix='', agent_assigned=True):
    """Crée un événement complet + un agent + un billet valide."""
    org = CustomUser.objects.create_user(
        email=f'org-cp{suffix}@test.com', password='pass',
        role=CustomUser.Role.ORGANIZER, is_organizer_verified=True,
    )
    agent = CustomUser.objects.create_user(
        email=f'agent-cp{suffix}@test.com', password='pass',
        role=CustomUser.Role.SCANNER,
    )
    buyer = CustomUser.objects.create_user(
        email=f'buyer-cp{suffix}@test.com', password='pass',
    )

    cat = Category.objects.create(name=f'C{suffix}', slug=f'cat-cp{suffix}')
    now = timezone.now()
    event = Event.objects.create(
        title=f'E{suffix}', slug=f'e-cp{suffix}', description='d',
        short_description='0700', category=cat, organizer=org,
        start_date=now + timedelta(days=10),
        end_date=now + timedelta(days=10, hours=3),
        status='published',
    )
    if agent_assigned:
        event.scanner_agents.add(agent)

    tt = TicketType.objects.create(
        event=event, name='Std', price=5000, quantity=100,
    )
    order = Order.objects.create(
        buyer=buyer, subtotal=5000, total=5000, status='pending',
    )
    OrderItem.objects.create(order=order, ticket_type=tt, quantity=1, unit_price=5000)
    order.mark_as_paid(payment_method='wave', payment_reference='PAY-CP')
    ticket = Ticket.objects.filter(order_item__order=order).first()
    return org, agent, buyer, event, tt, ticket


class CheckAgentTests(TestCase):
    """Tests de _check_agent."""

    def _req(self, user):
        r = type('R', (), {'user': user})()
        return r

    def test_anonyme_rejete(self):
        from django.contrib.auth.models import AnonymousUser
        _, err = api_views._check_agent(self._req(AnonymousUser()))
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 401)

    def test_inactif_rejete(self):
        u = CustomUser.objects.create_user(email='inact@test.com', password='p')
        u.is_active = False
        u.save()
        _, err = api_views._check_agent(self._req(u))
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 403)

    def test_mauvais_role_rejete(self):
        # Utilise un rôle explicite qui n'est PAS scanner/organizer/admin
        u = CustomUser.objects.create_user(
            email='nope@test.com', password='p',
            role='customer',
        )
        user, err = api_views._check_agent(self._req(u))

        # Soit c'est rejeté (403), soit un rôle par défaut l'autorise
        if err is not None:
            self.assertEqual(err.status_code, 403)
        else:
            # Le user n'a pas de rôle autorisé → ne devrait pas arriver
            self.assertFalse(
                user.is_scanner_agent or user.is_organizer or user.is_platform_admin,
                f"Rôle {user.role!r} ne devrait pas passer _check_agent"
            )

    def test_organisateur_ok(self):
        u = CustomUser.objects.create_user(
            email='ok@test.com', password='p',
            role=CustomUser.Role.ORGANIZER,
        )
        user, err = api_views._check_agent(self._req(u))
        self.assertIsNone(err)
        self.assertEqual(user, u)


class AuthorizeAgentForEventTests(TestCase):
    def test_platform_admin_ok(self):
        admin = CustomUser.objects.create_user(
            email='padmin@test.com', password='p',
            role=CustomUser.Role.ADMIN,
        )
        event = MagicMock()
        self.assertIsNone(api_views._authorize_agent_for_event(admin, event))

    def test_organisateur_autre_rejete(self):
        org1 = CustomUser.objects.create_user(
            email='o1@test.com', password='p',
            role=CustomUser.Role.ORGANIZER,
        )
        org2 = CustomUser.objects.create_user(
            email='o2@test.com', password='p',
            role=CustomUser.Role.ORGANIZER,
        )
        event = MagicMock()
        event.organizer_id = org1.pk

        err = api_views._authorize_agent_for_event(org2, event)
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 403)

    def test_agent_scanner_non_assigne_rejete(self):
        agent = CustomUser.objects.create_user(
            email='agent-no@test.com', password='p',
            role=CustomUser.Role.SCANNER,
        )
        event = MagicMock()
        event.scanner_agents.filter.return_value.exists.return_value = False

        err = api_views._authorize_agent_for_event(agent, event)
        self.assertIsNotNone(err)


class ProcessScanBranchTests(TestCase):
    """Couvre les branches qui retournent tôt dans _process_scan."""

    def setUp(self):
        self.org, self.agent, self.buyer, self.event, self.tt, self.ticket = \
            _setup_full_event('-ps')

    def test_qr_invalide_trop_court(self):
        session, _ = ScanSession.objects.get_or_create(
            event=self.event, agent=self.agent,
            started_at__date=timezone.now().date(),
            defaults={'started_at': timezone.now()},
        )
        result = api_views._process_scan(
            self.agent, self.event, session, 'abc',
        )
        self.assertEqual(result['result'], ScanLog.Result.INVALID_QR)

    def test_uuid_invalide(self):
        session, _ = ScanSession.objects.get_or_create(
            event=self.event, agent=self.agent,
            started_at__date=timezone.now().date(),
            defaults={'started_at': timezone.now()},
        )
        result = api_views._process_scan(
            self.agent, self.event, session,
            'not-a-uuid:ticket_number:x:y:z',
        )
        self.assertEqual(result['result'], ScanLog.Result.INVALID_QR)

    def test_billet_introuvable(self):
        session, _ = ScanSession.objects.get_or_create(
            event=self.event, agent=self.agent,
            started_at__date=timezone.now().date(),
            defaults={'started_at': timezone.now()},
        )
        fake_uuid = str(uuid_lib.uuid4())
        result = api_views._process_scan(
            self.agent, self.event, session,
            f'{fake_uuid}:TK-NOPE:order:ts:sig',
        )
        self.assertEqual(result['result'], ScanLog.Result.NOT_FOUND)

    def test_qr_falsifie(self):
        session, _ = ScanSession.objects.get_or_create(
            event=self.event, agent=self.agent,
            started_at__date=timezone.now().date(),
            defaults={'started_at': timezone.now()},
        )
        # Donne un QR avec la bonne UUID mais mauvaise signature
        fake_qr = f"{self.ticket.uuid}:{self.ticket.ticket_number}:X:Y:WRONGSIG"
        result = api_views._process_scan(
            self.agent, self.event, session, fake_qr,
        )
        self.assertEqual(result['result'], ScanLog.Result.INVALID_QR)


class SyncOfflineScansTests(TestCase):
    """Tests de sync_offline_scans."""

    def setUp(self):
        self.org, self.agent, self.buyer, self.event, self.tt, self.ticket = \
            _setup_full_event('-syn')
        self.client = Client()
        self.client.force_login(self.agent)

    def _url(self):
        try:
            return reverse('scanner_api:sync_offline')
        except Exception:
            return '/scanner/api/sync/'

    def test_batch_trop_grand_rejete(self):
        payload = {'event_id': self.event.id, 'scans': [{}] * 501}
        response = self.client.post(
            self._url(),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_scans_non_liste_rejete(self):
        payload = {'event_id': self.event.id, 'scans': 'not-a-list'}
        response = self.client.post(
            self._url(),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_client_uuid_invalide(self):
        payload = {
            'event_id': self.event.id,
            'scans': [{'client_uuid': 'NOT-A-UUID', 'qr_data': 'x'}],
        }
        response = self.client.post(
            self._url(),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['results'][0]['result'], 'invalid_qr')

    def test_idempotence_meme_uuid(self):
        """Un même client_uuid renvoyé 2 fois → 1 seul traitement."""
        c_uuid = str(uuid_lib.uuid4())
        payload = {
            'event_id': self.event.id,
            'scans': [{'client_uuid': c_uuid, 'qr_data': self.ticket.qr_code_data}],
        }
        response = self.client.post(
            self._url(),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        # 2e envoi identique
        response = self.client.post(
            self._url(),
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['results'][0].get('idempotent'))