"""
IvoirPass V2 — Fixe automatiquement le domaine du Site Django
(sinon Django reste sur 'example.com' par defaut, ce qui casse
les liens generes par allauth dans les emails).

Utilise ALLOWED_HOSTS[0], deja correctement configure par
environnement (.env) : localhost en dev, prepod.ivoirpass.com
en preprod, ivoirpass.com en production — sans variable
supplementaire a gerer.
"""
from django.db import migrations


def set_site_domain(apps, schema_editor):
    from django.conf import settings
    Site = apps.get_model('sites', 'Site')
    domain = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'ivoirpass.com'
    Site.objects.update_or_create(
        id=1,
        defaults={'domain': domain, 'name': 'IvoirPass'},
    )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(set_site_domain, reverse_noop),
    ]
