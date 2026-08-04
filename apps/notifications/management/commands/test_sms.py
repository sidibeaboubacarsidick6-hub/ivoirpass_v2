"""
Commande de diagnostic : envoie un vrai SMS de test pour vérifier que
les clés Orange SMS CI fonctionnent — sans avoir besoin de passer par
un vrai achat de billet.

Usage :
    python manage.py test_sms +2250700000000
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Envoie un SMS de test pour diagnostiquer la config Orange SMS CI"

    def add_arguments(self, parser):
        parser.add_argument('numero', type=str, help="Numéro au format +225XXXXXXXXXX")

    def handle(self, *args, **options):
        numero = options['numero']

        self.stdout.write("=" * 60)
        self.stdout.write("CONFIGURATION SMS ACTUELLE")
        self.stdout.write("=" * 60)
        self.stdout.write(f"SMS_ENABLED             : {settings.SMS_ENABLED}")
        self.stdout.write(f"ORANGE_SMS_CLIENT_ID     : {'défini (' + str(len(settings.ORANGE_SMS_CLIENT_ID)) + ' caractères)' if settings.ORANGE_SMS_CLIENT_ID else '(VIDE — PROBLÈME)'}")
        self.stdout.write(f"ORANGE_SMS_CLIENT_SECRET : {'défini (' + str(len(settings.ORANGE_SMS_CLIENT_SECRET)) + ' caractères)' if settings.ORANGE_SMS_CLIENT_SECRET else '(VIDE — PROBLÈME)'}")
        self.stdout.write(f"ORANGE_SMS_SENDER_NAME   : {settings.ORANGE_SMS_SENDER_NAME}")
        self.stdout.write("=" * 60)
        self.stdout.write("")

        if not settings.SMS_ENABLED:
            self.stdout.write(self.style.ERROR(
                "SMS_ENABLED=False — aucun SMS ne sera jamais envoyé, "
                "même avec de bonnes clés. Mets SMS_ENABLED=True dans ton .env."
            ))
            return

        if not settings.ORANGE_SMS_CLIENT_ID or not settings.ORANGE_SMS_CLIENT_SECRET:
            self.stdout.write(self.style.ERROR(
                "Clés Orange manquantes dans le .env — impossible d'envoyer."
            ))
            return

        self.stdout.write(f"Tentative d'envoi d'un SMS de test à {numero}...")
        self.stdout.write("")

        from apps.notifications.sms import OrangeSMSService

        # On teste directement le service Orange (pas la fonction send_sms
        # globale) pour voir précisément où ça bloque si ça bloque :
        # l'obtention du token OAuth, ou l'envoi du SMS lui-même.
        try:
            token = OrangeSMSService._get_token()
            if not token:
                self.stdout.write(self.style.ERROR(
                    "❌ ÉCHEC — Impossible d'obtenir un token OAuth Orange. "
                    "Vérifie que CLIENT_ID et CLIENT_SECRET sont corrects et actifs "
                    "sur https://developer.orange.com (portail développeur Orange)."
                ))
                return
            self.stdout.write(self.style.SUCCESS("✅ Token OAuth Orange obtenu avec succès."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ ÉCHEC lors de l'obtention du token : {type(e).__name__}: {e}"))
            return

        success = OrangeSMSService.send(numero, "IvoirPass : ceci est un SMS de test de configuration.")

        if success:
            self.stdout.write(self.style.SUCCESS(
                f"✅ SUCCÈS — SMS envoyé à {numero}. Vérifie le téléphone."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                "❌ ÉCHEC lors de l'envoi — regarde la ligne 'SMS Orange échec ...' "
                "juste au-dessus pour le code d'erreur exact renvoyé par Orange."
            ))