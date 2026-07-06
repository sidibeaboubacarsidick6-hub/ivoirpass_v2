# Migration 3/3 — à lancer SEULEMENT après avoir vérifié en base
# que les données ont bien été copiées (voir étape "Vérification" ci-dessous).
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0004_migrate_delivery_data'),  # ⚠️ nom réel de la migration 2
    ]

    operations = [
        migrations.RemoveField(
            model_name='productorder',
            name='delivery_address_old',
        ),
    ]
