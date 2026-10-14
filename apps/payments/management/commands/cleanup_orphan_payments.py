"""
Management command — Nettoyage des Payment PENDING orphelins.

Un Payment est dit "orphelin" s'il est PENDING alors que sa commande
associée (order / guest_order / product_order / guest_product_order)
est CANCELLED.

À lancer une fois après le déploiement du fix du 2026-10-14.

Usage :
    python manage.py cleanup_orphan_payments          # Simulation (dry-run)
    python manage.py cleanup_orphan_payments --apply  # Applique les changements
"""
from django.core.management.base import BaseCommand

from apps.payments.models import Payment


class Command(BaseCommand):
    help = "Annule les Payment PENDING dont la commande est CANCELLED."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help="Applique les modifications (sinon mode simulation)",
        )

    def handle(self, *args, **options):
        apply = options['apply']

        if not apply:
            self.stdout.write(self.style.WARNING(
                "Mode SIMULATION (dry-run). Utiliser --apply pour appliquer."
            ))
            self.stdout.write("")

        total = 0

        # On inspecte les Payment PENDING et on vérifie le statut de la commande
        pending_payments = Payment.objects.filter(
            status=Payment.Status.PENDING,
        ).select_related(
            'order', 'guest_order', 'product_order', 'guest_product_order'
        )

        for payment in pending_payments:
            order = (
                payment.order
                or payment.guest_order
                or payment.product_order
                or payment.guest_product_order
            )
            if order is None:
                continue
            if order.status == 'cancelled':
                self.stdout.write(
                    f"  Payment #{payment.id} ({order.order_number}) : "
                    f"PENDING → CANCELLED"
                )
                if apply:
                    payment.status = Payment.Status.CANCELLED
                    payment.save(update_fields=['status'])
                total += 1

        self.stdout.write("")
        if apply:
            self.stdout.write(self.style.SUCCESS(
                f"→ {total} Payment orphelin(s) nettoyé(s)."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"→ {total} Payment orphelin(s) détecté(s) "
                f"(aucune modification appliquée)."
            ))
