"""
Test d'audit — Phase 2 (back-office financier) & Phase 4 (rôles, immutabilité
du journal d'audit).

Couvre :
- CustomUser : nouveaux rôles Finance/Support/Auditeur et leurs propriétés
- AuditLog : immutabilité (ni modification, ni suppression, même via l'ORM)
- Back-office /dashboard/transactions/ : accès par rôle, filtrage, fiche
  détaillée, exports (CSV/Excel/PDF)

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_backoffice_financier_audit -v 2
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse

from apps.accounts.models import CustomUser
from apps.tickets.models import Order
from apps.payments.models import Payment
from apps.dashboard.models import AuditLog


class RolePropertiesTests(TestCase):
    def test_is_platform_staff_couvre_les_quatre_roles_internes(self):
        for role in (CustomUser.Role.ADMIN, CustomUser.Role.FINANCE,
                     CustomUser.Role.SUPPORT, CustomUser.Role.AUDITOR):
            user = CustomUser(role=role)
            self.assertTrue(user.is_platform_staff, f"{role} devrait être considéré comme personnel plateforme")

    def test_is_platform_staff_exclut_organisateur_et_scanner(self):
        for role in (CustomUser.Role.ORGANIZER, CustomUser.Role.SCANNER):
            user = CustomUser(role=role)
            self.assertFalse(user.is_platform_staff)

    def test_can_manage_platform_reserve_a_admin(self):
        self.assertTrue(CustomUser(role=CustomUser.Role.ADMIN).can_manage_platform)
        for role in (CustomUser.Role.FINANCE, CustomUser.Role.SUPPORT, CustomUser.Role.AUDITOR):
            self.assertFalse(
                CustomUser(role=role).can_manage_platform,
                f"{role} ne doit pas pouvoir agir, seulement consulter",
            )


class AuditLogImmutabilityTests(TestCase):
    def setUp(self):
        self.entry = AuditLog.objects.create(
            action=AuditLog.Action.PAYMENT_SUCCESS,
            description="Test",
            model_name='Payment', object_id='IP-TEST-001',
        )

    def test_modification_dune_entree_existante_est_refusee(self):
        self.entry.description = "Modifié frauduleusement"
        with self.assertRaises(PermissionDenied):
            self.entry.save()

    def test_suppression_instance_par_instance_est_refusee(self):
        with self.assertRaises(PermissionDenied):
            self.entry.delete()
        self.assertTrue(AuditLog.objects.filter(pk=self.entry.pk).exists())

    def test_suppression_en_masse_est_refusee(self):
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.all().delete()
        self.assertTrue(AuditLog.objects.filter(pk=self.entry.pk).exists())

    def test_creation_dune_nouvelle_entree_reste_possible(self):
        AuditLog.objects.create(action=AuditLog.Action.EXPORT, description="Nouvelle entrée")
        self.assertEqual(AuditLog.objects.count(), 2)


class TransactionsBackofficeAccessTests(TestCase):
    """Vérifie que chaque rôle a exactement l'accès prévu (lecture pour
    Admin/Finance/Support/Auditeur, rien pour Organisateur/Scanner)."""

    def setUp(self):
        for role, email in [
            (CustomUser.Role.ADMIN, 'admin@test.com'),
            (CustomUser.Role.FINANCE, 'finance@test.com'),
            (CustomUser.Role.SUPPORT, 'support@test.com'),
            (CustomUser.Role.AUDITOR, 'auditor@test.com'),
            (CustomUser.Role.ORGANIZER, 'organizer@test.com'),
            (CustomUser.Role.SCANNER, 'scanner@test.com'),
        ]:
            CustomUser.objects.create_user(email=email, password='Pass123!', role=role,
                                            first_name='T', last_name='User')

    def _login(self, email):
        c = Client()
        c.login(email=email, password='Pass123!')
        return c

    def test_admin_finance_support_auditor_accedent_a_la_liste(self):
        for email in ('admin@test.com', 'finance@test.com', 'support@test.com', 'auditor@test.com'):
            response = self._login(email).get(reverse('dashboard:transactions'))
            self.assertEqual(response.status_code, 200, f"{email} devrait avoir accès en lecture")

    def test_organisateur_et_scanner_nont_pas_acces(self):
        for email in ('organizer@test.com', 'scanner@test.com'):
            response = self._login(email).get(reverse('dashboard:transactions'))
            self.assertNotEqual(response.status_code, 200, f"{email} ne doit pas accéder au back-office financier")

    def test_visiteur_non_connecte_est_redirige(self):
        response = Client().get(reverse('dashboard:transactions'))
        self.assertNotEqual(response.status_code, 200)


class TransactionDetailAndFilterTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            email='admin2@test.com', password='Pass123!', role=CustomUser.Role.ADMIN,
        )
        self.buyer = CustomUser.objects.create_user(
            email='buyer.tx@test.com', password='Pass123!',
            first_name='Ache', last_name='Teur',
        )
        self.order = Order.objects.create(
            buyer=self.buyer, subtotal=Decimal('10000'), commission=Decimal('500'),
            total=Decimal('10000'), status=Order.Status.PAID,
        )
        self.payment = Payment.objects.create(
            order=self.order, amount=Decimal('10000'), currency='XOF',
            status=Payment.Status.COMPLETED, provider=Payment.Provider.PAYDUNYA,
            paydunya_token='tok_detail_test',
        )
        self.client_ = Client()
        self.client_.login(email='admin2@test.com', password='Pass123!')

    def test_fiche_transaction_saffiche(self):
        response = self.client_.get(reverse('dashboard:transaction_detail', args=[self.order.order_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)

    def test_reference_inconnue_redirige_proprement(self):
        response = self.client_.get(reverse('dashboard:transaction_detail', args=['IP-INCONNUE']))
        self.assertEqual(response.status_code, 302)

    def test_recherche_par_reference_filtre_correctement(self):
        response = self.client_.get(reverse('dashboard:transactions'), {'q': self.order.order_number})
        self.assertContains(response, self.order.order_number)

    def test_recherche_sans_correspondance_ne_remonte_rien(self):
        response = self.client_.get(reverse('dashboard:transactions'), {'q': 'REFERENCE-INEXISTANTE-XYZ'})
        self.assertNotContains(response, self.order.order_number)

    def test_export_csv_contient_les_metadonnees_obligatoires(self):
        response = self.client_.get(reverse('dashboard:export_transactions_csv'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        self.assertIn('Généré par', content)
        self.assertIn('Total net', content)
        self.assertIn(self.order.order_number, content)

    def test_export_excel_repond_200(self):
        response = self.client_.get(reverse('dashboard:export_transactions_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    def test_export_pdf_repond_200(self):
        response = self.client_.get(reverse('dashboard:export_transactions_pdf'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_hash_paydunya_est_masque_dans_la_fiche(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            raw_response={'status': 'completed', 'hash': 'secret_signature_hash_value'}
        )
        response = self.client_.get(reverse('dashboard:transaction_detail', args=[self.order.order_number]))
        self.assertNotContains(response, 'secret_signature_hash_value')
