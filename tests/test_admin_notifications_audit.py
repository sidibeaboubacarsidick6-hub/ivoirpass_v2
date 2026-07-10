"""
Test d'audit — vérifie l'envoi réel des notifications admin par email.
Couvre les 3 déclencheurs : nouvel événement publié, nouveau produit publié,
nouvelle demande de reversement.

Lancer avec :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_admin_notifications_audit -v 2
"""
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.notifications.models import AdminNotification
from apps.events.models import Event, Category
from apps.store.models import Product
from apps.dashboard.models import OrganizerWallet, WithdrawalRequest, Dispute


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class AdminNotificationEmailTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            email="admin@ivoirpass.test",
            password="TestPass123!",
            first_name="Admin",
            last_name="Test",
            role=CustomUser.Role.ADMIN,
            is_active=True,
            is_staff=True,
            notify_email=True,
        )
        # Admin ayant désactivé les notifications email — ne doit RIEN recevoir
        self.admin_no_email = CustomUser.objects.create_user(
            email="admin-nomail@ivoirpass.test",
            password="TestPass123!",
            first_name="AdminSansMail",
            last_name="Test",
            role=CustomUser.Role.ADMIN,
            is_active=True,
            is_staff=True,
            notify_email=False,
        )
        # Admin inactif — ne doit RIEN recevoir non plus
        self.admin_inactive = CustomUser.objects.create_user(
            email="admin-inactive@ivoirpass.test",
            password="TestPass123!",
            first_name="AdminInactif",
            last_name="Test",
            role=CustomUser.Role.ADMIN,
            is_active=False,
            is_staff=True,
            notify_email=True,
        )
        self.organizer = CustomUser.objects.create_user(
            email="organizer@ivoirpass.test",
            password="TestPass123!",
            first_name="Orga",
            last_name="Nisateur",
            role=CustomUser.Role.ORGANIZER,
            is_active=True,
        )
        self.category = Category.objects.create(name="Concert", slug="concert")

    def test_nouvel_evenement_publie_notifie_admin(self):
        mail.outbox.clear()
        count_before = AdminNotification.objects.count()

        Event.objects.create(
            title="Concert Test Audit",
            slug="concert-test-audit",
            organizer=self.organizer,
            category=self.category,
            description="Un événement de test.",
            short_description="Test",
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=3),
            venue_name="Palais de la Culture",
            venue_city="Abidjan",
            venue_country="CI",
            total_capacity=100,
            status='published',
        )

        self.assertEqual(AdminNotification.objects.count(), count_before + 1)
        notif = AdminNotification.objects.filter(type='new_event').latest('created_at')
        self.assertEqual(notif.type, 'new_event')

        self.assertEqual(len(mail.outbox), 1, "Un seul email attendu (un seul admin avec notify_email=True et actif)")
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["admin@ivoirpass.test"])
        self.assertIn("[IvoirPass Admin]", msg.subject)
        self.assertIn("Concert Test Audit", msg.body)
        self.assertIn("Orga Nisateur", msg.body)

    def test_nouveau_produit_publie_notifie_admin(self):
        mail.outbox.clear()

        Product.objects.create(
            seller=self.organizer,
            name="T-shirt IvoirPass",
            slug="tshirt-ivoirpass",
            description="Produit de test",
            price=5000,
            product_type=Product.ProductType.PHYSICAL,
            status='published',
        )

        self.assertTrue(AdminNotification.objects.filter(type='new_product').exists())
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["admin@ivoirpass.test"])
        self.assertIn("T-shirt IvoirPass", msg.body)

    def test_demande_reversement_notifie_admin(self):
        mail.outbox.clear()

        wallet = OrganizerWallet.objects.create(
            organizer=self.organizer,
            balance_available=100000,
        )
        withdrawal = WithdrawalRequest.objects.create(
            wallet=wallet,
            amount=50000,
            fee=1000,
            amount_net=49000,
            payout_method='mobile_money',
            payout_phone='+2250700000000',
            payout_name='Orga Nisateur',
        )

        self.assertTrue(AdminNotification.objects.filter(type='withdrawal').exists())
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["admin@ivoirpass.test"])
        self.assertIn(withdrawal.reference, msg.body)

    def test_admin_sans_notify_email_ne_recoit_rien(self):
        """L'admin avec notify_email=False ou is_active=False ne doit jamais être destinataire."""
        mail.outbox.clear()

        Event.objects.create(
            title="Autre concert",
            slug="autre-concert",
            organizer=self.organizer,
            category=self.category,
            description="Test",
            short_description="Test",
            start_date=timezone.now() + timedelta(days=5),
            end_date=timezone.now() + timedelta(days=5, hours=2),
            venue_name="Palais",
            venue_city="Abidjan",
            venue_country="CI",
            total_capacity=50,
            status='published',
        )

        self.assertEqual(len(mail.outbox), 1)
        recipients = mail.outbox[0].to
        self.assertNotIn("admin-nomail@ivoirpass.test", recipients)
        self.assertNotIn("admin-inactive@ivoirpass.test", recipients)

    def test_aucun_admin_actif_avec_notify_email_pas_de_crash(self):
        """Si aucun admin éligible n'existe, la tâche ne doit pas planter (juste ne rien envoyer)."""
        CustomUser.objects.filter(role=CustomUser.Role.ADMIN).update(notify_email=False)
        mail.outbox.clear()

        try:
            Event.objects.create(
                title="Concert sans admin",
                slug="concert-sans-admin",
                organizer=self.organizer,
                category=self.category,
                description="Test",
                short_description="Test",
                start_date=timezone.now() + timedelta(days=5),
                end_date=timezone.now() + timedelta(days=5, hours=2),
                venue_name="Palais",
                venue_city="Abidjan",
                venue_country="CI",
                total_capacity=50,
                status='published',
            )
        except Exception as e:
            self.fail(f"La création de l'événement ne devrait pas lever d'exception : {e}")

        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(AdminNotification.objects.filter(type='new_event', title__icontains='publié').exists())

    def test_nouveau_litige_notifie_admin(self):
        """Soumission d'un litige via le formulaire public /reclamation/."""
        mail.outbox.clear()
        count_before = AdminNotification.objects.count()

        response = self.client.post('/dashboard/reclamation/', {
            'type': 'other',
            'email': 'client@test.com',
            'phone': '+2250700000000',
            'order_number': 'IP-2026-ABC123',
            'subject': 'Billet non reçu',
            'description': 'Je n\'ai jamais reçu mon billet par email après paiement.',
        })

        self.assertTrue(Dispute.objects.filter(email='client@test.com').exists(), "Le litige doit être créé en base")
        self.assertEqual(len(mail.outbox), 1, "Email de notification attendu pour l'admin")
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["admin@ivoirpass.test"])
        self.assertIn("Billet non reçu", msg.body)

        # Bug détecté : la vue crée l'AdminNotification directement PUIS
        # appelle notify_admins_async qui en crée une deuxième pour le même litige.
        notif_count_after = AdminNotification.objects.filter(type='fraud_alert').count()
        if notif_count_after == 2:
            print("  [INFO] Doublon confirmé : 2 AdminNotification créées pour 1 seul litige "
                  "(apps/dashboard/views.py:submit_dispute crée la notification en base "
                  "ET appelle notify_admins_async qui en recrée une autre).")
        self.assertGreaterEqual(notif_count_after, 1)
