"""
Commande de diagnostic : déclenche une fausse erreur pour vérifier que
Sentry la capture bien — sans exposer d'URL publique de test en prod.

Usage :
    python manage.py test_sentry
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Déclenche une erreur de test pour vérifier la capture Sentry"

    def handle(self, *args, **options):
        if not settings.SENTRY_DSN:
            self.stdout.write(self.style.ERROR(
                "SENTRY_DSN n'est pas défini dans ton .env — Sentry est désactivé, "
                "rien ne sera envoyé. Ajoute SENTRY_DSN=... puis relance le serveur."
            ))
            return

        self.stdout.write(f"SENTRY_DSN détecté, tentative d'envoi d'une erreur de test...")

        try:
            1 / 0
        except ZeroDivisionError as e:
            import sentry_sdk
            event_id = sentry_sdk.capture_exception(e)
            self.stdout.write(self.style.SUCCESS(
                f"✅ Erreur envoyée à Sentry (id: {event_id}). "
                f"Va voir dans l'onglet 'Issues' de ton projet Sentry — "
                f"ça peut prendre quelques secondes à apparaître."
            ))