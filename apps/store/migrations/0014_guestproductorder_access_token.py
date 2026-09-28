# Migration manuelle — pattern Django pour ajouter un champ unique
# avec un default callable (voir :
# https://docs.djangoproject.com/en/4.2/howto/writing-migrations/
# #migrations-that-add-unique-fields
#
# Le AddField direct avec unique=True échouait : toutes les lignes
# existantes recevaient le MÊME UUID au moment du ALTER TABLE, puis la
# création de l'index unique violait la contrainte. On procède en 3
# temps : AddField sans unique → RunPython qui backfill un UUID unique
# par ligne → AlterField qui pose la contrainte unique.

from django.db import migrations, models
import uuid


def gen_unique_access_tokens(apps, schema_editor):
    """Génère un access_token unique pour chaque GuestProductOrder existant."""
    GuestProductOrder = apps.get_model('store', 'GuestProductOrder')
    for row in GuestProductOrder.objects.all():
        row.access_token = uuid.uuid4()
        row.save(update_fields=['access_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0013_alter_product_cover_image_alter_product_digital_file_and_more'),
    ]

    operations = [
        # 1. Ajouter le champ sans contrainte unique (null=True temporaire)
        migrations.AddField(
            model_name='guestproductorder',
            name='access_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text='Jeton secret pour les URLs publiques — ne pas exposer.',
                null=True,
                verbose_name="jeton d'accès",
            ),
        ),
        # 2. Backfill : un UUID unique par ligne
        migrations.RunPython(
            gen_unique_access_tokens,
            reverse_code=migrations.RunPython.noop,
        ),
        # 3. Contrainte unique + retour à non-nullable
        migrations.AlterField(
            model_name='guestproductorder',
            name='access_token',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text='Jeton secret pour les URLs publiques — ne pas exposer.',
                unique=True,
                verbose_name="jeton d'accès",
            ),
        ),
    ]