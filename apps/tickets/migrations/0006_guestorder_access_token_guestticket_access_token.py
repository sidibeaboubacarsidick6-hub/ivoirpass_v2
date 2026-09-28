"""
Migration manuelle — pattern Django pour ajouter 2 champs uniques avec
default callable (voir :
https://docs.djangoproject.com/en/4.2/howto/writing-migrations/
#migrations-that-add-unique-fields

Concerne GuestOrder.access_token et GuestTicket.access_token — jetons
secrets pour les URLs publiques (fix IDOR 2026-09-28).
"""
from django.db import migrations, models
import uuid


def gen_order_tokens(apps, schema_editor):
    GuestOrder = apps.get_model('tickets', 'GuestOrder')
    for row in GuestOrder.objects.all():
        row.access_token = uuid.uuid4()
        row.save(update_fields=['access_token'])


def gen_ticket_tokens(apps, schema_editor):
    GuestTicket = apps.get_model('tickets', 'GuestTicket')
    for row in GuestTicket.objects.all():
        row.access_token = uuid.uuid4()
        row.save(update_fields=['access_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0005_guestticket_online_access_token'),
    ]

    operations = [
        # ── GuestOrder.access_token ─────────────────────────────────
        migrations.AddField(
            model_name='guestorder',
            name='access_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text="Jeton secret pour les URLs publiques — ne pas exposer.",
                null=True,
                verbose_name="jeton d'accès",
            ),
        ),
        migrations.RunPython(gen_order_tokens, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='guestorder',
            name='access_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text="Jeton secret pour les URLs publiques — ne pas exposer.",
                unique=True,
                verbose_name="jeton d'accès",
            ),
        ),

        # ── GuestTicket.access_token ────────────────────────────────
        migrations.AddField(
            model_name='guestticket',
            name='access_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text="Jeton secret pour le PDF du billet — ne pas exposer.",
                null=True,
                verbose_name="jeton d'accès",
            ),
        ),
        migrations.RunPython(gen_ticket_tokens, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='guestticket',
            name='access_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text="Jeton secret pour le PDF du billet — ne pas exposer.",
                unique=True,
                verbose_name="jeton d'accès",
            ),
        ),
    ]