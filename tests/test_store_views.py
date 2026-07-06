"""
Tests pour les vues de la boutique
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import CustomUser
from apps.store.models import Product, ProductCategory, ProductOrder


class StoreViewsTest(TestCase):
    """Tests pour les vues de la boutique"""
    
    def setUp(self):
        self.client = Client()
        
        # Créer les utilisateurs
        self.seller = CustomUser.objects.create_user(
            email='seller@test.com',
            password='IvoirPass2026!',
            role='organizer',
        )
        self.buyer = CustomUser.objects.create_user(
            email='buyer@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        
        # Créer une catégorie
        self.category = ProductCategory.objects.create(
            name='Livres',
            slug='livres',
            icon='bi-book',
        )
        
        # Créer un produit
        self.product = Product.objects.create(
            name='Ebook Test',
            description='Description du produit',
            seller=self.seller,
            category=self.category,
            product_type='digital',
            price=5000,
            status='published',
            stock=10,
            download_limit=3,
            download_expiry_hours=48,
        )
    
    # ============================================================
    # TESTS POUR store_list
    # ============================================================
    
    def test_store_list_public(self):
        """Test que la liste des produits est publique"""
        response = self.client.get(reverse('store:list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'store/list.html')
        self.assertIn('products', response.context)
    
    def test_store_list_shows_published_products(self):
        """Test que seuls les produits publiés sont affichés"""
        # Créer un produit non publié
        Product.objects.create(
            name='Produit caché',
            description='Test',
            seller=self.seller,
            category=self.category,
            product_type='digital',
            price=1000,
            status='draft',
        )
        
        response = self.client.get(reverse('store:list'))
        products = response.context['products']
        # Seul le produit publié doit être visible
        self.assertEqual(products.count(), 1)
        self.assertEqual(products.first().name, 'Ebook Test')
    
    # ============================================================
    # TESTS POUR store_detail
    # ============================================================
    
    def test_store_detail_public(self):
        """Test que le détail d'un produit est public"""
        response = self.client.get(
            reverse('store:detail', args=[self.product.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'store/detail.html')
        self.assertEqual(response.context['product'], self.product)
    
    def test_store_detail_not_found(self):
        """Test de détail avec produit inexistant"""
        response = self.client.get(
            reverse('store:detail', args=['produit-inexistant'])
        )
        self.assertEqual(response.status_code, 404)
    
    # ============================================================
    # TESTS POUR buy_product
    # ============================================================
    
    def test_buy_product_requires_login(self):
        """Test que l'achat nécessite une connexion"""
        response = self.client.get(
            reverse('store:buy', args=[self.product.slug])
        )
        self.assertEqual(response.status_code, 302)  # Redirection login
    
    def test_buy_product_success(self):
        """Test d'achat de produit"""
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:buy', args=[self.product.slug]),
            {'quantity': 2}
        )
        # Redirige vers le paiement ou confirmation
        self.assertEqual(response.status_code, 302)
    
    def test_buy_product_out_of_stock(self):
        """Test d'achat de produit en rupture de stock"""
        self.product.stock = 0
        self.product.save()
        
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:buy', args=[self.product.slug]),
            {'quantity': 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'stock')
    
    def test_buy_product_wrong_user(self):
        """Test d'achat par un autre utilisateur"""
        other_user = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:buy', args=[self.product.slug]),
            {'quantity': 1}
        )
        self.assertEqual(response.status_code, 302)
    
    # ============================================================
    # TESTS POUR my_orders
    # ============================================================
    
    def test_my_orders_requires_login(self):
        """Test que la liste des commandes nécessite une connexion"""
        response = self.client.get(reverse('store:my_orders'))
        self.assertEqual(response.status_code, 302)
    
    def test_my_orders_success(self):
        """Test de la liste des commandes"""
        # Créer une commande
        ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=2,
            unit_price=5000,
            subtotal=10000,
            total=10000,
            status='completed',
        )
        
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('store:my_orders'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'store/orders.html')
        self.assertIn('orders', response.context)
        self.assertEqual(response.context['orders'].count(), 1)
    
    def test_my_orders_empty(self):
        """Test de la liste des commandes vide"""
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('store:my_orders'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['orders'].count(), 0)
    
    # ============================================================
    # TESTS POUR order_detail
    # ============================================================
    
    def test_order_detail_requires_login(self):
        """Test que le détail de commande nécessite une connexion"""
        order = ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1,
            unit_price=5000,
            subtotal=5000,
            total=5000,
        )
        response = self.client.get(
            reverse('store:order_detail', args=[order.order_number])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_order_detail_success(self):
        """Test du détail d'une commande"""
        order = ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1,
            unit_price=5000,
            subtotal=5000,
            total=5000,
        )
        
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('store:order_detail', args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'store/order_detail.html')
        self.assertEqual(response.context['order'], order)
    
    def test_order_detail_wrong_user(self):
        """Test du détail de commande par un autre utilisateur"""
        order = ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1,
            unit_price=5000,
            subtotal=5000,
            total=5000,
        )
        
        other_user = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='participant',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('store:order_detail', args=[order.order_number])
        )
        self.assertIn(response.status_code, [302, 403, 404])
    
    # ============================================================
    # TESTS POUR my_products (seller)
    # ============================================================
    
    def test_my_products_requires_login(self):
        """Test que la liste des produits nécessite une connexion"""
        response = self.client.get(reverse('store:my_products'))
        self.assertEqual(response.status_code, 302)
    
    def test_my_products_requires_seller_role(self):
        """Test que seul un seller peut voir ses produits"""
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('store:my_products'))
        self.assertIn(response.status_code, [302, 403])
    
    def test_my_products_success(self):
        """Test de la liste des produits (seller)"""
        self.client.login(email='seller@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('store:my_products'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'store/my_products.html')
        self.assertIn('products', response.context)
        self.assertEqual(response.context['products'].count(), 1)
    
    # ============================================================
    # TESTS POUR product_create
    # ============================================================
    
    def test_product_create_requires_login(self):
        """Test que la création nécessite une connexion"""
        response = self.client.get(reverse('store:product_create'))
        self.assertEqual(response.status_code, 302)
    
    def test_product_create_requires_seller_role(self):
        """Test que seul un seller peut créer un produit"""
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(reverse('store:product_create'))
        self.assertIn(response.status_code, [302, 403])
    
    def test_product_create_success(self):
        """Test de création d'un produit"""
        self.client.login(email='seller@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:product_create'),
            {
                'name': 'Nouveau produit',
                'description': 'Description',
                'category': self.category.id,
                'product_type': 'digital',
                'price': 10000,
                'status': 'published',
                'download_limit': 5,
                'download_expiry_hours': 72,
            }
        )
        self.assertEqual(response.status_code, 302)  # Redirection
        self.assertTrue(Product.objects.filter(name='Nouveau produit').exists())
    
    # ============================================================
    # TESTS POUR product_edit
    # ============================================================
    
    def test_product_edit_requires_login(self):
        """Test que la modification nécessite une connexion"""
        response = self.client.get(
            reverse('store:product_edit', args=[self.product.slug])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_product_edit_success(self):
        """Test de modification d'un produit"""
        self.client.login(email='seller@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:product_edit', args=[self.product.slug]),
            {
                'name': 'Produit modifié',
                'description': 'Nouvelle description',
                'category': self.category.id,
                'product_type': 'digital',
                'price': 15000,
                'status': 'published',
            }
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Produit modifié')
        self.assertEqual(self.product.price, 15000)
    
    def test_product_edit_wrong_user(self):
        """Test de modification par un autre seller"""
        other_seller = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='organizer',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('store:product_edit', args=[self.product.slug])
        )
        self.assertIn(response.status_code, [302, 403, 404])
    
    # ============================================================
    # TESTS POUR product_delete
    # ============================================================
    
    def test_product_delete_requires_login(self):
        """Test que la suppression nécessite une connexion"""
        response = self.client.post(
            reverse('store:product_delete', args=[self.product.slug])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_product_delete_success(self):
        """Test de suppression d'un produit"""
        self.client.login(email='seller@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:product_delete', args=[self.product.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(id=self.product.id).exists())
    
    def test_product_delete_wrong_user(self):
        """Test de suppression par un autre seller"""
        other_seller = CustomUser.objects.create_user(
            email='other@test.com',
            password='IvoirPass2026!',
            role='organizer',
        )
        self.client.login(email='other@test.com', password='IvoirPass2026!')
        
        response = self.client.post(
            reverse('store:product_delete', args=[self.product.slug])
        )
        self.assertIn(response.status_code, [302, 403, 404])
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())
    
    # ============================================================
    # TESTS POUR download_file
    # ============================================================
    
    def test_download_file_requires_login(self):
        """Test que le téléchargement nécessite une connexion"""
        # Créer une commande
        order = ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1,
            unit_price=5000,
            subtotal=5000,
            total=5000,
            status='completed',
        )
        # Créer un lien de téléchargement
        link = order.create_download_link()
        
        response = self.client.get(
            reverse('store:download', args=[link.token])
        )
        self.assertEqual(response.status_code, 302)
    
    def test_download_file_success(self):
        """Test de téléchargement d'un fichier"""
        order = ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1,
            unit_price=5000,
            subtotal=5000,
            total=5000,
            status='completed',
        )
        link = order.create_download_link()
        
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('store:download', args=[link.token])
        )
        self.assertEqual(response.status_code, 200)
    
    def test_download_file_expired(self):
        """Test de téléchargement avec lien expiré"""
        order = ProductOrder.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1,
            unit_price=5000,
            subtotal=5000,
            total=5000,
            status='completed',
        )
        link = order.create_download_link()
        # Expirer le lien
        link.expires_at = timezone.now() - timedelta(hours=1)
        link.save()
        
        self.client.login(email='buyer@test.com', password='IvoirPass2026!')
        
        response = self.client.get(
            reverse('store:download', args=[link.token])
        )
        self.assertEqual(response.status_code, 404)

