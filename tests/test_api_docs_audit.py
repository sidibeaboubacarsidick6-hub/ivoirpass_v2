from django.test import TestCase, Client
from apps.accounts.models import CustomUser

class APIDocsTest(TestCase):
    def test_swagger_protege_non_connecte(self):
        client = Client()
        response = client.get('/api/docs/')
        print("\nSans connexion:", response.status_code)
        self.assertIn(response.status_code, (302, 403))

    def test_swagger_accessible_admin(self):
        admin = CustomUser.objects.create_user(email='admindoc@t.com', password='x', is_staff=True, is_active=True)
        client = Client()
        client.force_login(admin)
        response = client.get('/api/docs/')
        print("Connecté admin:", response.status_code)
        self.assertEqual(response.status_code, 200)
