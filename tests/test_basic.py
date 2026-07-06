from django.test import TestCase

class BasicTest(TestCase):
    def test_simple(self):
        """Test simple pour vérifier que les tests fonctionnent"""
        self.assertTrue(True)
    
    def test_math(self):
        """Test mathématique simple"""
        self.assertEqual(2 + 2, 4)
