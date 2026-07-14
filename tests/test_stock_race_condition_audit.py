"""
Test d'audit — Anti-survente (Phase 5 du script de test MVP).
Vérifie qu'un seul acheteur peut obtenir le dernier billet en stock,
même en cas d'achats simultanés (race condition).

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
from apps.tickets.models import Order


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


class StockOversellSequentialTests(TestCase):
    """Vérifie qu'un deuxième achat séquentiel est bien refusé une fois le stock épuisé."""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-stock@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.buyer1 = CustomUser.objects.create_user(email='buyer1-stock@test.com', password='Pass123!')
        self.buyer2 = CustomUser.objects.create_user(email='buyer2-stock@test.com', password='Pass123!')
        self.event, self.ticket_type = _setup_event_last_ticket(self.organizer)

    def _add_to_cart_and_checkout(self, client):
        client.get(reverse('tickets:add_to_cart', args=[self.ticket_type.id]))
        return client.post(reverse('tickets:checkout'))

    def test_deuxieme_achat_refuse_une_fois_stock_epuise(self):
        c1 = Client(); c1.force_login(self.buyer1)
        c2 = Client(); c2.force_login(self.buyer2)

        self._add_to_cart_and_checkout(c1)
        self.ticket_type.refresh_from_db()
        self.assertEqual(self.ticket_type.quantity_sold, 1, "Le premier achat doit consommer le dernier billet")

        orders_before = Order.objects.filter(buyer=self.buyer2).count()
        self._add_to_cart_and_checkout(c2)
        orders_after = Order.objects.filter(buyer=self.buyer2).count()

        self.assertEqual(orders_before, orders_after, "Aucune commande ne doit être créée si le stock est épuisé")
        self.ticket_type.refresh_from_db()
        self.assertLessEqual(
            self.ticket_type.quantity_sold, self.ticket_type.quantity,
            "quantity_sold ne doit jamais dépasser quantity (pas de survente)"
        )


class StockOversellConcurrencyTests(TransactionTestCase):
    """Deux acheteurs qui tentent d'acheter LE MÊME dernier billet en même temps."""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='orga-stock-conc@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
        )
        self.buyer1 = CustomUser.objects.create_user(email='buyer1-conc@test.com', password='Pass123!')
        self.buyer2 = CustomUser.objects.create_user(email='buyer2-conc@test.com', password='Pass123!')
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

        def buy(buyer):
            client = Client()
            client.force_login(buyer)
            client.get(reverse('tickets:add_to_cart', args=[self.ticket_type.id]))
            response = client.post(reverse('tickets:checkout'))
            results.append(response.status_code)

        t1 = threading.Thread(target=buy, args=(self.buyer1,))
        t2 = threading.Thread(target=buy, args=(self.buyer2,))
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.ticket_type.refresh_from_db()
        self.assertLessEqual(
            self.ticket_type.quantity_sold, self.ticket_type.quantity,
            f"Survente détectée : quantity_sold={self.ticket_type.quantity_sold} > quantity={self.ticket_type.quantity}"
        )
        orders_count = Order.objects.filter(
            buyer__in=[self.buyer1, self.buyer2], status=Order.Status.PENDING
        ).count()
        self.assertEqual(orders_count, 1, f"Une seule commande doit réussir sur les deux tentatives simultanées, obtenu : {orders_count}")
