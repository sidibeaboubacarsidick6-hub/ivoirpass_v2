from django.db import migrations, models

def migrate_statuses(apps, schema_editor):
    WithdrawalRequest = apps.get_model("dashboard", "WithdrawalRequest")
    WithdrawalRequest.objects.filter(status="approved").update(status="processing")
    WithdrawalRequest.objects.filter(status="processed").update(status="completed")

class Migration(migrations.Migration):
    dependencies = [("dashboard", "0007_auditlog_metadata_and_actions")]
    operations = [
        migrations.AddField(model_name="withdrawalrequest", name="provider", field=models.CharField(default="paydunya", max_length=30, verbose_name="provider")),
        migrations.AddField(model_name="withdrawalrequest", name="provider_token", field=models.CharField(blank=True, max_length=200, verbose_name="token provider")),
        migrations.AddField(model_name="withdrawalrequest", name="provider_transaction_id", field=models.CharField(blank=True, max_length=200, verbose_name="transaction provider")),
        migrations.AddField(model_name="withdrawalrequest", name="provider_reference", field=models.CharField(blank=True, max_length=200, verbose_name="référence provider")),
        migrations.AddField(model_name="withdrawalrequest", name="provider_status", field=models.CharField(blank=True, max_length=30, verbose_name="statut provider")),
        migrations.AddField(model_name="withdrawalrequest", name="retry_count", field=models.PositiveIntegerField(default=0, verbose_name="nombre de retries")),
        migrations.AddField(model_name="withdrawalrequest", name="last_error", field=models.TextField(blank=True, verbose_name="dernière erreur")),
        migrations.AddField(model_name="withdrawalrequest", name="completed_at", field=models.DateTimeField(blank=True, null=True, verbose_name="date de confirmation")),
        migrations.AlterField(model_name="withdrawalrequest", name="status", field=models.CharField(choices=[("pending", "En attente de validation OTP"), ("processing", "Reversement en cours"), ("completed", "Reversement réussi"), ("failed", "Reversement échoué"), ("cancelled", "Reversement annulé"), ("rejected", "Rejetée")], default="pending", max_length=20, verbose_name="statut")),
        migrations.RunPython(migrate_statuses, migrations.RunPython.noop),
    ]
