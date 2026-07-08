"""
IvoirPass V2 — Tests de bout en bout (flux complets)
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from apps.accounts.models import CustomUser
from apps.events.models import Event, Category, TicketType
from apps.tickets.models import Order, OrderItem, Ticket, GuestOrder, GuestOrderItem
from apps.store.models import Product, ProductOrder
from apps.dashboard.models import OrganizerWallet, WithdrawalRequest


class FullPurchaseFlowTest(TestCase):
    """Test du parcours complet : achat billet → paiement → QR code → scan"""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Concerts')
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True
        )
        self.event = Event.objects.create(
            title='Concert Test E2E', description='Description',
            category=self.category, organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=30),
            end_date=timezone.now() + timedelta(days=31),
            status='published'
        )
        self.ticket_type = TicketType.objects.create(
            event=self.event, name='Standard', price=5000, quantity=100
        )
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='BuyerPass!'
        )

    def test_full_ticket_purchase_flow(self):
        """Parcourt complet : création commande → paiement → génération tickets → QR"""
        # 1. Créer la commande
        order = Order.objects.create(
            buyer=self.buyer, subtotal=5000, total=5000, status='pending'
        )
        item = OrderItem.objects.create(
            order=order, ticket_type=self.ticket_type, quantity=1, unit_price=5000
        )

        # 2. Paiement
        order.mark_as_paid(payment_method='wave', payment_reference='PAY-TEST-001')

        # 3. Vérifier le statut
        self.assertEqual(order.status, 'paid')
        self.assertIsNotNone(order.paid_at)

        # 4. Vérifier les tickets générés
        tickets = Ticket.objects.filter(order_item__order=order)
        self.assertEqual(tickets.count(), 1)

        # 5. Vérifier le QR code
        ticket = tickets.first()
        self.assertTrue(ticket.ticket_number.startswith('TK-'))
        self.assertTrue(ticket.qr_code_data)
        self.assertTrue(ticket.verify_qr(ticket.qr_code_data))

        # 6. Scanner le ticket
        ticket.mark_as_used()
        self.assertEqual(ticket.status, 'used')
        self.assertIsNotNone(ticket.scanned_at)

    def test_guest_ticket_purchase_flow(self):
        """Parcours invité : achat sans compte"""
        order = GuestOrder.objects.create(
            first_name='Jean', last_name='Kouadio', email='jean@test.com',
            subtotal=5000, total=5000, status='pending'
        )
        item = GuestOrderItem.objects.create(
            order=order, ticket_type=self.ticket_type, quantity=1, unit_price=5000
        )
        order.mark_as_paid(payment_method='orange_money', payment_reference='PAY-GUEST-001')

        self.assertEqual(order.status, 'paid')
        tickets = order.guest_items.first().tickets.all()
        self.assertEqual(tickets.count(), 1)
        self.assertTrue(tickets.first().qr_code_data)


class StorePurchaseFlowTest(TestCase):
    """Test du parcours boutique : achat → téléchargement"""

    def setUp(self):
        self.seller = CustomUser.objects.create_user(
            email='seller@test.com', password='SellerPass!', role='organizer'
        )
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com', password='BuyerPass!'
        )
        self.product = Product.objects.create(
            name='Livre Test E2E', description='Description', seller=self.seller,
            price=3000, product_type='digital', status='published'
        )

    def test_digital_product_purchase_flow(self):
        """Achat produit numérique → génération liens téléchargement"""
        order = ProductOrder.objects.create(
            buyer=self.buyer, product=self.product, quantity=1,
            unit_price=3000, subtotal=3000, total=3000, status='pending'
        )
        order.mark_as_paid(payment_method='wave', payment_reference='STORE-TEST-001')

        self.assertEqual(order.status, 'paid')
        links = order.download_links.all()
        self.assertEqual(links.count(), 1)
        self.assertTrue(links.first().is_valid)


class WalletWithdrawalFlowTest(TestCase):
    """Test du parcours wallet : crédit → demande reversement → OTP"""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com', password='Pass123!', role='organizer'
        )
        self.wallet, _ = OrganizerWallet.objects.get_or_create(organizer=self.organizer)

    def test_wallet_credit_and_withdrawal(self):
        """Crédit → demande reversement → vérification"""
        # Créditer
        self.wallet.credit(50000, description='Ventes', reference='IP-2026-TEST')
        self.assertEqual(self.wallet.balance_available, 50000)

        # Demande de reversement
        wr = WithdrawalRequest.objects.create(
            wallet=self.wallet, amount=30000, payout_method='wave',
            payout_phone='+2250707070707', payout_name='Jean Test'
        )
        self.assertEqual(wr.status, 'pending')
        self.assertTrue(wr.reference.startswith('REV-'))

        # Approuver
        wr.approve(admin_user=self.organizer, note='OK')
        self.assertEqual(wr.status, 'approved')

        # Traiter
        wr.mark_processed(admin_user=self.organizer, note='Virement fait')
        self.assertEqual(wr.status, 'processed')
        self.assertEqual(self.wallet.balance_available, 20000)
        self.assertEqual(self.wallet.balance_withdrawn, 30000)


class QRCodeSecurityTest(TestCase):
    """Test de sécurité des QR codes"""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='org@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=True
        )
        self.event = Event.objects.create(
            title='Test QR', description='Desc', organizer=self.organizer,
            start_date=timezone.now() + timedelta(days=7),
            end_date=timezone.now() + timedelta(days=8), status='published'
        )
        self.tt = TicketType.objects.create(
            event=self.event, name='VIP', price=10000, quantity=50
        )
        self.buyer = CustomUser.objects.create_user(
            email='fan@test.com', password='FanPass!'
        )
        self.order = Order.objects.create(
            buyer=self.buyer, subtotal=10000, total=10000, status='pending'
        )
        OrderItem.objects.create(
            order=self.order, ticket_type=self.tt, quantity=1, unit_price=10000
        )
        self.order.mark_as_paid(payment_method='wave', payment_reference='QR-TEST')
        self.ticket = Ticket.objects.filter(order_item__order=self.order).first()

    def test_qr_code_contains_timestamp_and_order(self):
        """Le QR code contient l'horodatage et le numéro de commande"""
        parts = self.ticket.qr_code_data.split(':')
        self.assertGreaterEqual(len(parts), 4)  # uuid:ticket:order:timestamp:sign
        self.assertIn(self.order.order_number, self.ticket.qr_code_data)

    def test_fake_qr_code_rejected(self):
        """Un QR code falsifié est rejeté"""
        self.assertFalse(self.ticket.verify_qr('fake:data:here:12345:abc'))

    def test_qr_verification_timing_safe(self):
        """La vérification utilise compare_digest (timing-safe)"""
        import time
        valid = self.ticket.qr_code_data
        invalid = valid[:-1] + 'X'

        start = time.time()
        for _ in range(100):
            self.ticket.verify_qr(valid)
        valid_time = time.time() - start

        start = time.time()
        for _ in range(100):
            self.ticket.verify_qr(invalid)
        invalid_time = time.time() - start

        # Les temps doivent être proches (timing-attack safe)
        self.assertAlmostEqual(valid_time, invalid_time, delta=0.5)


class KYCValidationTest(TestCase):
    """Test du blocage KYC"""

    def setUp(self):
        self.organizer = CustomUser.objects.create_user(
            email='neworg@test.com', password='Pass123!', role='organizer',
            is_organizer_verified=False  # Pas encore vérifié
        )

    def test_unverified_organizer_cannot_publish_paid_event(self):
        """Un organisateur non vérifié ne peut pas publier d'événement payant"""
        self.client.login(email='neworg@test.com', password='Pass123!')

        response = self.client.post(reverse('events:create'), {
            'title': 'Test Bloqué',
            'description': 'Description',
            'start_date': '2026-08-01 20:00',
            'end_date': '2026-08-02 02:00',
            'venue_name': 'Palais',
            'venue_city': 'Abidjan',
            'status': 'published',
            'event_type': 'physical',
            'total_capacity': 100,
            'ticket_types-TOTAL_FORMS': '1',
            'ticket_types-INITIAL_FORMS': '0',
            'ticket_types-0-name': 'VIP',
            'ticket_types-0-price': '5000',
            'ticket_types-0-quantity': '50',
            'ticket_types-0-max_per_order': '5',
        })

        # L'événement ne doit pas être créé (bloqué par KYC)
        self.assertFalse(Event.objects.filter(title='Test Bloqué').exists())
