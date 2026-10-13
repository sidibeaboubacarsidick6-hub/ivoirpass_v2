"""
Management command — Seed des catégories d'événements par défaut.

Usage :
    python manage.py seed_categories

Idempotent : utilise get_or_create() pour ne créer que les catégories
manquantes. Peut être lancé à tout moment sans risque de doublon.

À lancer après un reset de base de données (par exemple via
`python manage.py migrate` suivi de `python manage.py seed_categories`).
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.events.models import Category


DEFAULT_CATEGORIES = [
    # (name, icon, color, order)
    ("Concerts",    "bi-music-note-beamed", "#1B7A3E", 1),
    ("Cinéma",      "bi-camera-video",      "#F47920", 2),
    ("Sport",       "bi-trophy",            "#0d6efd", 3),
    ("Théâtre",     "bi-masks",             "#6f42c1", 4),
    ("Formation",   "bi-mortarboard",       "#20c997", 5),
    ("Conférence",  "bi-mic",               "#fd7e14", 6),
    ("Festival",    "bi-stars",             "#e83e8c", 7),
    ("Autre",       "bi-tag",               "#6c757d", 99),
]


class Command(BaseCommand):
    help = "Crée les catégories d'événements par défaut si elles n'existent pas."

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0

        for name, icon, color, order in DEFAULT_CATEGORIES:
            slug = slugify(name, allow_unicode=False)
            obj, created = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'icon': icon,
                    'color': color,
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
