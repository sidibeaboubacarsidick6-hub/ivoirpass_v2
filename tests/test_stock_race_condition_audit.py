"""
Test d'audit — Anti-survente (Phase 5 du script de test MVP).
Vérifie qu'un seul acheteur peut obtenir le dernier billet en stock,
même en cas d'achats simultanés (race condition).

✅ H-3 (audit) : ces tests ciblaient à l'origine le tunnel d'achat "avec
compte" (add_to_cart + checkout), retiré car mort (toujours remplacé par
un simple redirect vers 'home'). Ils ont été réécrits pour exercer le
tunnel réellement actif : guest_checkout — la protection anti-survente
(select_for_update) est strictement la même dans les deux tunnels.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_stock_race_condition_audit -v 2
"""
import threading
from datetime import timedelta

from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import GuestOrder


def _setup_event_last_ticket(organizer):
    category = Category.objects.create(name='Concert Stock Test', slug='concert-stock-test')
    event = Event.objects.create(
        title='Concert Dernier Billet', description='Test', category=category,
        organizer=organizer,
        start_date=timezone.now() + timedelta(days=10),
        end_date=timezone.now() + timedelta(days=10, hours=3),
        status='published',
    )
    # Un seul billet en stock, déjà 0 vendu -> il en reste exactement 1.
    ticket_type = TicketType.objects.create(event=event, name='Dernier', price=5000, quantity=1, quantity_sold=0)
    return event, ticket_type


def _guest_checkout_post(client, event, ticket_type, email):
    return client.post(
        reverse('tickets:guest_checkout', args=[event.slug]),
        {
            'first_name': 'Test',
            'last_name': 'Acheteur',
            'email': email,
            'phone': '0700000000',
            f'quantity_{ticket_type.pk}': 1,
        },
    )


class StockOversellSequentialTests(TestCase):
    """Vérifie qu'un deuxième achat séquentiel est bien refusé une fois le stock épuisé."""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-stock@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.event, self.ticket_type = _setup_event_last_ticket(self.organizer)

    def test_deuxieme_achat_refuse_une_fois_stock_epuise(self):
        c1 = Client()
        c2 = Client()

        _guest_checkout_post(c1, self.event, self.ticket_type, 'buyer1-stock@test.com')
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.quantity_sold, 1, "Le premier achat doit consommer le dernier billet")

        orders_before = GuestOrder.objects.filter(email='buyer2-stock@test.com').count()
        _guest_checkout_post(c2, self.event, self.ticket_type, 'buyer2-stock@test.com')
        orders_after = GuestOrder.objects.filter(email='buyer2-stock@test.com').count()

        self.assertEqual(orders_before, orders_after, "Aucune commande ne doit être créée si le stock est épuisé")
        self.ticket_type.refresh_from_db()
        self.assertLessEqual(
            self.ticket_type.quantity_sold, self.ticket_type.quantity,
            "quantity_sold ne doit jamais dépasser quantity (pas de survente)"
        )


class StockOversellConcurrencyTests(TransactionTestCase):
    """Deux acheteurs invités qui tentent d'acheter LE MÊME dernier billet en même temps."""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-stock-conc@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.event, self.ticket_type = _setup_event_last_ticket(self.organizer)

    def test_deux_achats_simultanes_du_dernier_billet(self):
        from django.db import connection

        if connection.vendor != 'postgresql':
            self.skipTest(
                "Ce test nécessite Postgres pour un vrai verrouillage de ligne "
                "(select_for_update). Lancez-le contre une vraie base Postgres "
                "pour valider la garantie anti-survente en conditions réelles."
            )

        results = []

        def buy(email):
            client = Client()
            response = _guest_checkout_post(client, self.event, self.ticket_type, email)
            results.append(response.status_code)

        t1 = threading.Thread(target=buy, args=('buyer1-conc@test.com',))
        t2 = threading.Thread(target=buy, args=('buyer2-conc@test.com',))
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.ticket_type.refresh_from_db()
        self.assertLessEqual(
            self.ticket_type.quantity_sold, self.ticket_type.quantity,
            f"Survente détectée : quantity_sold={self.ticket_type.quantity_sold} > quantity={self.ticket_type.quantity}"
        )
        orders_count = GuestOrder.objects.filter(
            email__in=['buyer1-conc@test.com', 'buyer2-conc@test.com'],
        ).count()
        self.assertEqual(orders_count, 1, f"Une seule commande doit réussir sur les deux tentatives simultanées, obtenu : {orders_count}")
