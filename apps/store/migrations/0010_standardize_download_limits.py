"""
IvoirPass V2 — Standardise les reglages de telechargement sur TOUS
les produits existants (3 telechargements, 48h). Ce reglage n'est
plus personnalisable par l'organisateur (retire du formulaire) ;
cette migration aligne aussi les produits crees avant ce changement,
qui pouvaient avoir des valeurs differentes.
"""
from django.db import migrations


def standardize_downloads(apps, schema_editor):
    Product = apps.get_model('store', 'Product')
    Product.objects.all().update(
        download_limit=3,
        download_expiry_hours=48,
    )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0009_alter_guestproductorder_delivery_method'),
    ]

    operations = [
        migrations.RunPython(standardize_downloads, reverse_noop),
    ]
