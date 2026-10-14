"""
Test du command seed_product_categories.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.store.models import ProductCategory


class SeedProductCategoriesTests(TestCase):

    def test_seed_creates_categories(self):
        """Le command crée les 12 catégories si aucune n'existe."""
        self.assertEqual(ProductCategory.objects.count(), 0)

        out = StringIO()
        call_command('seed_product_categories', stdout=out)

        self.assertEqual(ProductCategory.objects.count(), 12)
        self.assertTrue(ProductCategory.objects.filter(slug='livres').exists())
        self.assertTrue(ProductCategory.objects.filter(slug='musique').exists())
        self.assertTrue(ProductCategory.objects.filter(slug='autre').exists())

    def test_seed_is_idempotent(self):
        """Un 2e lancement ne duplique rien."""
        call_command('seed_product_categories')
        count_after_first = ProductCategory.objects.count()

        out = StringIO()
        call_command('seed_product_categories', stdout=out)

        self.assertEqual(ProductCategory.objects.count(), count_after_first)
        self.assertIn("0 catégorie(s) créée(s)", out.getvalue())
