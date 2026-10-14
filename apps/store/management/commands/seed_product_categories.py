"""
Management command — Seed des catégories boutique par défaut.

Usage :
    python manage.py seed_product_categories

Idempotent : utilise get_or_create() pour ne créer que les catégories
manquantes. Peut être lancé à tout moment sans risque de doublon.

À lancer après un reset de base de données.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.store.models import ProductCategory


DEFAULT_PRODUCT_CATEGORIES = [
    # (name, icon, order)
    ("Livres",                "bi-book",             1),
    ("Musique",               "bi-music-note-beamed", 2),
    ("Art & Artisanat",       "bi-palette",          3),
    ("Mode & Vêtements",      "bi-bag",              4),
    ("Beauté & Bien-être",    "bi-stars",            5),
    ("Électronique",          "bi-phone",            6),
    ("Alimentation",          "bi-basket",           7),
    ("Sport & Loisirs",       "bi-bicycle",          8),
    ("Formations & Cours",    "bi-mortarboard",      9),
    ("Jeux vidéo",            "bi-controller",       10),
    ("Maison & Déco",         "bi-house",            11),
    ("Autre",                 "bi-tag",              99),
]


class Command(BaseCommand):
    help = "Crée les catégories boutique par défaut si elles n'existent pas."

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0

        for name, icon, order in DEFAULT_PRODUCT_CATEGORIES:
            slug = slugify(name, allow_unicode=False)
            obj, created = ProductCategory.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'icon': icon,
                    'order': order,
                    'is_active': True,
                    'description': '',
                },
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Créée : {name} ({slug})"))
            else:
                existing_count += 1
                self.stdout.write(f"  · Déjà existante : {name} ({slug})")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"→ {created_count} catégorie(s) créée(s), "
            f"{existing_count} déjà existante(s)."
        ))
