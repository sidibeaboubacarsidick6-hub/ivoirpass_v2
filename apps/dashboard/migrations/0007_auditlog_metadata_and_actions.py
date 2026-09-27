# Migration écrite à la main (pas d'accès réseau dans cet environnement
# pour exécuter `makemigrations`). Merci de lancer
# `python manage.py makemigrations --check --dry-run` en local avant de
# migrer, pour confirmer qu'elle correspond exactement à l'état des modèles.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0006_reversalotp_attempts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('create', 'Création'), ('update', 'Modification'), ('delete', 'Suppression'),
                    ('publish', 'Publication'), ('unpublish', 'Dépublier'),
                    ('login', 'Connexion'), ('logout', 'Déconnexion'),
                    ('payout', 'Reversement'), ('export', 'Export données'), ('scan', 'Scan QR'),
                    ('order_created', 'Commande créée'), ('order_cancelled', 'Commande annulée'),
                    ('order_refunded', 'Commande remboursée'),
                    ('payment_initiated', 'Paiement initié'), ('payment_success', 'Paiement réussi'),
                    ('payment_failed', 'Paiement échoué'), ('payment_cancelled', 'Paiement annulé'),
                    ('ticket_created', 'Billet(s) généré(s)'), ('ticket_scanned', 'Billet scanné'),
                    ('email_sent', 'Email envoyé'), ('email_failed', 'Email échoué'),
                    ('other', 'Autre'),
                ],
                max_length=30,
                verbose_name='action',
            ),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='metadata',
            field=models.JSONField(blank=True, null=True, verbose_name='métadonnées'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['model_name', 'object_id', '-created_at'], name='dashboard_auditlog_obj_idx'),
        ),
    ]
