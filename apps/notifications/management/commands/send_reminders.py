"""
IvoirPass V2 — Commande de rappel J-1
Lance avec : python manage.py send_reminders
Planifier avec cron : 0 9 * * * python manage.py send_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Envoie les rappels J-1 pour les événements de demain"

    def handle(self, *args, **options):
        from apps.tickets.models import Ticket
        from apps.notifications.service import NotificationService

        # Cible les événements qui commencent demain
        tomorrow_start = (timezone.now() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0
        )
        tomorrow_end = tomorrow_start.replace(hour=23, minute=59, second=59)

        # Récupère les tickets valides pour ces événements
        tickets = Ticket.objects.filter(
            status='valid',
            order_item__order__status='paid',
            order_item__ticket_type__event__start_date__range=(
                tomorrow_start, tomorrow_end
            )
        ).select_related(
            'order_item__ticket_type__event',
            'order_item__order__buyer'
        )

        count   = 0
        errors  = 0

        for ticket in tickets:
            try:
                if ticket.buyer.notify_email:
                    NotificationService.event_reminder(ticket)
                    count += 1
            except Exception as e:
                errors += 1
                logger.error(f"Rappel erreur ticket {ticket.pk}: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ {count} rappel(s) envoyé(s). "
                f"{errors} erreur(s)."
            )
        )