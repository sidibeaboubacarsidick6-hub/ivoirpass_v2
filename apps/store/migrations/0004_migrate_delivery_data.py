# Migration 2/3 — data migration, à renommer (ex: 0016_...)
from django.db import migrations


def copy_delivery_data(apps, schema_editor):
    ProductOrder = apps.get_model('store', 'ProductOrder')

    orders = ProductOrder.objects.filter(
        delivery_address_old__isnull=False
    ).select_related('delivery_address_old')

    for order in orders:
        addr = order.delivery_address_old
        if not addr:
            continue

        order.delivery_name = getattr(addr, 'full_name', '') or ''

        # Concatène address_line1 + address_line2 dans le TextField unique
        line1 = getattr(addr, 'address_line1', '') or ''
        line2 = getattr(addr, 'address_line2', '') or ''
        order.delivery_address = (
            f"{line1}\n{line2}".strip() if line2 else line1
        )

        order.delivery_city = getattr(addr, 'city', '') or ''

        # Champs absents du modèle UserAddress connu à ce jour —
        # laissés vides. Si UserAddress possède phone/commune/country,
        # remplace les lignes ci-dessous en conséquence :
        order.delivery_phone = getattr(addr, 'phone', '') or ''
        order.delivery_commune = getattr(addr, 'commune', '') or ''
        order.delivery_country = getattr(
            addr, 'country', "Côte d'Ivoire"
        ) or "Côte d'Ivoire"

        order.save(update_fields=[
            'delivery_name', 'delivery_address', 'delivery_city',
            'delivery_phone', 'delivery_commune', 'delivery_country',
        ])


def reverse_noop(apps, schema_editor):
    # Pas de retour arrière automatique — l'ancien FK reste intact
    # jusqu'à la migration 3, donc rien à faire ici.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0003_add_new_delivery_fields'),  # ⚠️ nom réel de la migration 1
    ]

    operations = [
        migrations.RunPython(copy_delivery_data, reverse_noop),
    ]
