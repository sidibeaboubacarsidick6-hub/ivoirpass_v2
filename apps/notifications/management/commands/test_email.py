"""
Commande de diagnostic : envoie un vrai email de test et affiche l'erreur
complète si ça échoue — au lieu de la chercher dans les logs du serveur.

Usage :
    python manage.py test_email ton_email@exemple.com
"""
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings


class Command(BaseCommand):
    help = "Envoie un email de test pour diagnostiquer la config SMTP"

    def add_arguments(self, parser):
        parser.add_argument('destinataire', type=str, help="Adresse email qui recevra le test")

    def handle(self, *args, **options):
        destinataire = options['destinataire']

        self.stdout.write("=" * 60)
        self.stdout.write("CONFIGURATION EMAIL ACTUELLE")
        self.stdout.write("=" * 60)
        self.stdout.write(f"EMAIL_BACKEND       : {settings.EMAIL_BACKEND}")
        self.stdout.write(f"EMAIL_HOST          : {getattr(settings, 'EMAIL_HOST', '(non défini)')}")
        self.stdout.write(f"EMAIL_PORT          : {getattr(settings, 'EMAIL_PORT', '(non défini)')}")
        self.stdout.write(f"EMAIL_USE_TLS       : {getattr(settings, 'EMAIL_USE_TLS', '(non défini)')}")
        self.stdout.write(f"EMAIL_HOST_USER     : {getattr(settings, 'EMAIL_HOST_USER', '(non défini)') or '(VIDE)'}")
        pwd = getattr(settings, 'EMAIL_HOST_PASSWORD', '')
        self.stdout.write(f"EMAIL_HOST_PASSWORD : {'*' * len(pwd) if pwd else '(VIDE — PROBLEME PROBABLE)'} ({len(pwd)} caractères)")
        self.stdout.write(f"DEFAULT_FROM_EMAIL  : {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write("=" * 60)
        self.stdout.write("")
        self.stdout.write(f"Tentative d'envoi d'un email à {destinataire}...")
        self.stdout.write("")

        try:
            send_mail(
                subject='[IvoirPass] Test de configuration email',
                message="Si tu reçois ce message, la configuration email fonctionne correctement.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[destinataire],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(
                f"✅ SUCCÈS — l'email a été envoyé sans erreur à {destinataire}. "
                f"Vérifie sa boîte de réception (et ses spams)."
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"❌ ÉCHEC — voici l'erreur exacte à copier-coller :\n"
            ))
            self.stdout.write(self.style.ERROR(f"{type(e).__name__}: {e}"))
            self.stdout.write("")
            self.stdout.write("Copie tout ce bloc et envoie-le, ça permettra de trouver la cause précise.")