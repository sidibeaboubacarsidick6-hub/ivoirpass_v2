# Migration 1/3 — à renommer avec le bon numéro (ex: 0015_...)
# et à adapter le champ `dependencies` avec le nom de ta dernière migration.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0002_product_commission_negotiated_and_more'),  # ⚠️ à remplacer par ta vraie dernière migration
    ]

    operations = [
        # 1. On renomme l'ancien FK pour libérer le nom "delivery_address"
        migrations.RenameField(
            model_name='productorder',
            old_name='delivery_address',
            new_name='delivery_address_old',
        ),
        # 2. On ajoute les nouveaux champs texte
        migrations.AddField(
            model_name='productorder',
            name='delivery_name',
            field=models.CharField(
                blank=True, max_length=200, verbose_name='nom destinataire'
            ),
        ),
        migrations.AddField(
            model_name='productorder',
            name='delivery_phone',
            field=models.CharField(
                blank=True, max_length=20, verbose_name='téléphone'
            ),
        ),
        migrations.AddField(
            model_name='productorder',
            name='delivery_address',
            field=models.TextField(
                blank=True, default='', verbose_name='adresse complète'
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='productorder',
            name='delivery_city',
            field=models.CharField(
                blank=True, max_length=100, verbose_name='ville'
            ),
        ),
        migrations.AddField(
            model_name='productorder',
            name='delivery_commune',
            field=models.CharField(
                blank=True, max_length=100, verbose_name='commune'
            ),
        ),
        migrations.AddField(
            model_name='productorder',
            name='delivery_country',
            field=models.CharField(
                blank=True, default="Côte d'Ivoire",
                max_length=100, verbose_name='pays'
            ),
        ),
        migrations.AddField(
            model_name='productorder',
            name='delivery_instructions',
            field=models.TextField(
                blank=True, default='', verbose_name='instructions'
            ),
            preserve_default=False,
        ),
    ]
