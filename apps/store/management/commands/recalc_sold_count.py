"""
IvoirPass V2 — Recalcul du champ Product.sold_count.

À lancer UNE FOIS après le fix du 2026-09-29 pour corriger les compteurs
faux (les ventes numériques n'étaient pas comptées).

Utilisation :
    python manage.py recalc_sold_count           # dry-run (affichage)
    python manage.py recalc_sold_count --apply   # applique les changements
"""
from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.store.models import Product, GuestProductOrder


class Command(BaseCommand):
    help = "Recalcule Product.sold_count à partir des commandes PAID."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help="Applique réellement les changements (sinon dry-run).",
        )

    def handle(self, *args, **options):
        apply = options['apply']

        if not apply:
            self.stdout.write(self.style.WARNING(
                "MODE DRY-RUN — aucun changement ne sera écrit. "
                "Ajoutez --apply pour appliquer."
            ))
            self.stdout.write("")

        total_fixed = 0
        total_checked = 0

        for product in Product.objects.all().order_by('id'):
            total_checked += 1

            # Somme des ventes PAID (guest tunnel actif)
            real = (
                GuestProductOrder.objects
                .filter(product=product, status=GuestProductOrder.Status.PAID)
                .aggregate(t=Sum('quantity'))['t'] or 0
            )

            if product.sold_count != real:
                self.stdout.write(
                    f"[#{product.id}] {product.name[:50]:<50} "
                    f"actuel={product.sold_count:<5} → corrigé={real}"
                )
                if apply:
                    Product.objects.filter(pk=product.pk).update(sold_count=real)
                total_fixed += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Produits vérifiés : {total_checked}"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"Produits corrigés : {total_fixed}"
        ))

        if not apply and total_fixed > 0:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "Relancez avec --apply pour appliquer les corrections."
            ))