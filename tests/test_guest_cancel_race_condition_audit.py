"""
Test d'audit — CRITIQUE : une commande billetterie invitée annulée par
l'acheteur ne doit plus jamais pouvoir se confirmer toute seule plus tard
(ex: via la tâche de réconciliation périodique).

Avant le correctif :
- guest_payment_cancel() changeait order.status en CANCELLED, mais ne
  touchait jamais le Payment associé (resté PENDING) ni n'enregistrait de
  timestamp d'annulation.
- GuestOrder.mark_as_paid() ne vérifiait que "déjà payée ?", jamais
  "annulée ?".
- reconcile_pending_payments() (toutes les ~20 min) retombait sur ce
  Payment resté PENDING, revérifiait chez PayDunya, obtenait "completed",
  et confirmait la commande malgré son annulation — billets compris.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_guest_cancel_race_condition_audit -v 2
"""
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.payments.models import Payment
from apps.tickets.models import GuestOrder, GuestOrderItem


def _make_pending_guest_order():
    organizer = CustomUser.objects.create_user(
        email='orga-cancel-race@test.com', password='Pass123!', role='organizer', is_organizer_verified=True,
    )
    category = Category.objects.create(name='Concert Annulation', slug='concert-annulation')
    event = Event.objects.create(
        title='Concert Annulation', description='Test', category=category,
        organizer=organizer,
        start_date=timezone.now() + timedelta(days=10),
        end_date=timezone.now() + timedelta(days=10, hours=3),
        status='published',
    )
    ticket_type = TicketType.objects.create(event=event, name='Standard', price=5000, quantity=50, quantity_sold=0)
    order = GuestOrder.objects.create(
        first_name='Test', last_name='Annulation', email='buyer-cancel-race@test.com',
        subtotal=5000, total=5000, status=GuestOrder.Status.PENDING,
    )
    GuestOrderItem.objects.create(order=order, ticket_type=ticket_type, quantity=1, unit_price=5000, subtotal=5000)
    payment = Payment.objects.create(
        guest_order=order, amount=5000, provider=Payment.Provider.PAYDUNYA,
        status=Payment.Status.PENDING, paydunya_token='fake-token-cancel-race',
    )
    return order, payment, ticket_type


class GuestOrderCancelThenReconcileTests(TestCase):
    """Le scénario exact signalé : annulation, puis tentative de confirmation tardive."""

    def test_commande_annulee_ne_peut_plus_etre_confirmee_par_mark_as_paid(self):
        order, payment, ticket_type = _make_pending_guest_order()

        Client().get(reverse('tickets:guest_cancel', kwargs={'order_number': order.order_number}))

        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.CANCELLED)
        self.assertIsNotNone(order.payment_cancelled_at, "Le timestamp d'annulation doit être enregistré")
        self.assertEqual(
            payment.status, Payment.Status.CANCELLED,
            "Le Payment associé doit lui aussi passer à CANCELLED, sinon la réconciliation le retrouve",
        )

        # Simule exactement ce que fait reconcile_pending_payments() quand
        # PayDunya répond "completed" pour ce token, quelques minutes plus
        # tard : c'est ici que la commande ressuscitait avant le correctif.
        newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference=payment.paydunya_token)

        self.assertFalse(newly_confirmed, "mark_as_paid() doit refuser une commande annulée récemment")
        order.refresh_from_db()
        self.assertEqual(order.status, GuestOrder.Status.CANCELLED, "Le statut ne doit jamais redevenir PAID")
        self.assertEqual(order.guest_items.first().tickets.count(), 0, "Aucun billet ne doit être généré")

    def test_commande_annulee_exclue_des_candidats_de_reconciliation(self):
        """Le Payment CANCELLED ne doit plus jamais être repris par la tâche de réconciliation."""
        order, payment, ticket_type = _make_pending_guest_order()
        Client().get(reverse('tickets:guest_cancel', kwargs={'order_number': order.order_number}))

        candidates = Payment.objects.filter(status=Payment.Status.PENDING, pk=payment.pk)
        self.assertEqual(candidates.count(), 0, "Un paiement annulé ne doit plus apparaître PENDING")

    def test_confirmation_plus_de_2h_apres_annulation_reste_bloquee(self):
        """La fenêtre de sécurité est bien de 2h, pas illimitée mais pas nulle non plus."""
        order, payment, ticket_type = _make_pending_guest_order()
        order.mark_payment_cancelled()
        order.status = GuestOrder.Status.CANCELLED
        order.save(update_fields=['status'])

        order.payment_cancelled_at = timezone.now() - timedelta(hours=3)
        order.save(update_fields=['payment_cancelled_at'])

        self.assertFalse(order.is_payment_cancelled(), "Après 2h, la fenêtre de sécurité expire")
        # Note : le statut reste CANCELLED indépendamment de la fenêtre —
        # mark_as_paid() vérifie is_payment_cancelled() ET status == PENDING,
        # donc une commande CANCELLED reste bloquée même après 2h, par le
        # garde-fou de statut (pas seulement par la fenêtre temporelle).
        newly_confirmed = order.mark_as_paid(payment_method='paydunya', payment_reference='autre-token')
        self.assertFalse(newly_confirmed, "Une commande CANCELLED ne redevient jamais PAID, même après 2h")
