"""
Vague 3.1 — Split du wallet en portefeuilles Événements / Boutique.

Historique (décision Q1) : les soldes existants sont entièrement
attribués au portefeuille Événements.
"""
from django.db import migrations, models


def copy_legacy_to_events(apps, schema_editor):
    """Copie balance_available → balance_events_available
              balance_pending   → balance_events_pending"""
    OrganizerWallet = apps.get_model('dashboard', 'OrganizerWallet')
    for w in OrganizerWallet.objects.all():
        w.balance_events_available = w.balance_available
        w.balance_events_pending = w.balance_pending
        w.save(update_fields=[
            'balance_events_available', 'balance_events_pending',
        ])


def reverse_copy(apps, schema_editor):
    """Rollback : remet les soldes événements dans les champs globaux."""
    OrganizerWallet = apps.get_model('dashboard', 'OrganizerWallet')
    for w in OrganizerWallet.objects.all():
        w.balance_available = w.balance_events_available
        w.balance_pending = w.balance_events_pending
        w.save(update_fields=['balance_available', 'balance_pending'])


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0014_alter_auditlog_action'),
    ]

    operations = [
        # 1. Ajouter les 4 nouveaux champs
        migrations.AddField(
            model_name='organizerwallet',
            name='balance_events_available',
            field=models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name='solde événements disponible'),
        ),
        migrations.AddField(
            model_name='organizerwallet',
            name='balance_events_pending',
            field=models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name='solde événements en attente'),
        ),
        migrations.AddField(
            model_name='organizerwallet',
            name='balance_store_available',
            field=models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name='solde boutique disponible'),
        ),
        migrations.AddField(
            model_name='organizerwallet',
            name='balance_store_pending',
            field=models.DecimalField(decimal_places=0, default=0, max_digits=14, verbose_name='solde boutique en attente'),
        ),

        # 2. Ajouter source sur WalletTransaction et WithdrawalRequest
        migrations.AddField(
            model_name='wallettransaction',
            name='source',
            field=models.CharField(
                choices=[('events', 'Événements'), ('store', 'Boutique'), ('legacy', 'Legacy (avant Vague 3.1)')],
                db_index=True, default='legacy', max_length=20,
                verbose_name='source',
            ),
        ),
        migrations.AddField(
            model_name='withdrawalrequest',
            name='source',
            field=models.CharField(
                choices=[('events', 'Événements'), ('store', 'Boutique')],
                default='events', max_length=20,
                verbose_name='source du reversement',
            ),
        ),

        # 3. Copier les données (historique → Événements)
        migrations.RunPython(copy_legacy_to_events, reverse_copy),

        # 4. Supprimer les anciens champs globaux
        migrations.RemoveField(model_name='organizerwallet', name='balance_available'),
        migrations.RemoveField(model_name='organizerwallet', name='balance_pending'),
    ]