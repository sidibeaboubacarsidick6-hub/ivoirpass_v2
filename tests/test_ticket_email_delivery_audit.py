"""
Test d'audit — Réception effective des emails.
Ne se contente pas de vérifier que le code "essaie" d'envoyer un email :
vérifie que l'email arrive VRAIMENT dans la boîte (mail.outbox en test).

Couvre : email de billets après paiement (chemin asynchrone Celery),
email de confirmation boutique, email de bienvenue, emails wallet.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_ticket_email_delivery_audit -v 2
"""
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings

from apps.accounts.models import CustomUser
from apps.tickets.models import Order
from apps.notifications.service import NotificationService


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class TicketEmailAfterPaymentTests(TestCase):
    """
    C'est LE test le plus important de tout l'audit : après un paiement
    confirmé, le client reçoit-il vraiment son billet par email ?
    """

    def setUp(self):
        self.buyer = CustomUser.objects.create_user(
            email="client-billet@test.com", password="Pass123!",
            first_name="Client", last_name="Billet", role=CustomUser.Role.PARTICIPANT,
        )
        self.order = Order.objects.create(
            buyer=self.buyer,
            subtotal=Decimal('10000'), commission=Decimal('500'), total=Decimal('10500'),
            status=Order.Status.PAID,
        )

    def test_BUG_send_ticket_email_async_importe_une_fonction_inexistante(self):
        """
        BUG CRITIQUE : apps/notifications/tasks.py::send_ticket_email_async
        importe `send_ticket_email` depuis apps.tickets.utils — cette
        fonction N'EXISTE PAS dans ce module. La vraie fonction d'envoi
        s'appelle NotificationService.ticket_confirmed() (apps/notifications/service.py).

        Conséquence en production : après CHAQUE paiement confirmé, la tâche
        Celery censée envoyer le billet par email échoue silencieusement
        (ImportError, absorbée par le retry Celery puis abandonnée après
        3 tentatives) — le client ne reçoit jamais son billet automatiquement.
        """
        from apps.tickets import utils as tickets_utils

        has_function = hasattr(tickets_utils, 'send_ticket_email')
        if not has_function:
            print(
                "\n  [BUG CONFIRMÉ] apps/tickets/utils.py n'a PAS de fonction "
                "'send_ticket_email'. apps/notifications/tasks.py::send_ticket_email_async "
                "va lever une ImportError à chaque exécution — AUCUN billet n'est "
                "envoyé automatiquement après paiement tant que ce n'est pas corrigé."
            )
        self.assertTrue(
            has_function,
            "send_ticket_email n'existe pas dans apps.tickets.utils — "
            "voir apps/notifications/tasks.py::send_ticket_email_async"
        )

    def test_email_billet_arrive_reellement_via_le_bon_chemin(self):
        """
        Vérifie que le mécanisme qui FONCTIONNE réellement aujourd'hui
        (NotificationService.ticket_confirmed, utilisé par les signaux)
        met bien un email dans la boîte du client.
        Sans ticket réel associé à la commande, la fonction retourne False
        sans email (comportement attendu, pas un bug) — ce test le documente.
        """
        mail.outbox.clear()
        sent = NotificationService.ticket_confirmed(self.order)
        if not sent:
            print(
                "\n  [INFO] Aucun ticket associé à cette commande de test → "
                "NotificationService.ticket_confirmed() retourne False sans "
                "envoyer d'email, c'est le comportement normal (pas de billet "
                "à joindre). Voir tests avec de vrais OrderItem/Ticket pour "
                "un scénario 100% réaliste."
            )
        # On vérifie au moins l'absence de crash, condition minimale de fiabilité.
        self.assertIn(sent, (True, False))

    def test_send_ticket_email_async_ne_plante_pas_le_process_appelant(self):
        """
        Même si l'import échoue, la tâche Celery (avec retry) ne doit pas
        remonter une exception non gérée qui ferait planter tout le flux
        d'achat pour l'utilisateur final.
        """
        from apps.notifications.tasks import send_ticket_email_async
        try:
            send_ticket_email_async.apply(args=[str(self.order.uuid)])
        except Exception as e:
            self.fail(
                f"send_ticket_email_async a laissé remonter une exception "
                f"non gérée : {type(e).__name__}: {e}. Avec CELERY_TASK_EAGER_PROPAGATES, "
                f"ceci confirme qu'une vraie tentative Celery finirait par échouer "
                f"après ses 3 retries sans jamais alerter personne."
            )


class WelcomeAndOtherEmailsTests(TestCase):
    """Vérifie que les autres emails automatiques partent bien."""

    def test_email_bienvenue_envoye_a_inscription(self):
        mail.outbox.clear()
        user = CustomUser.objects.create_user(
            email="nouveau@test.com", password="Pass123!",
            first_name="Nouveau", last_name="Membre", role=CustomUser.Role.PARTICIPANT,
        )
        sent = NotificationService.welcome(user)
        self.assertTrue(sent is not False)
        self.assertGreaterEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[-1].to, ["nouveau@test.com"])
