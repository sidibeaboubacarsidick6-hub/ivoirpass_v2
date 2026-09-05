# Migration écrite à la main (pas d'accès réseau dans cet environnement
# pour exécuter `makemigrations`). Merci de lancer
# `python manage.py makemigrations --check --dry-run` en local avant de
# migrer, pour confirmer qu'elle correspond exactement à l'état des modèles.
# Purement additif : 3 nouvelles tables, aucune colonne existante touchée.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0004_tickettype_valid_date'),
    ]

    operations = [
        migrations.CreateModel(
            name='EventFAQ',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question', models.CharField(max_length=300, verbose_name='question')),
                ('answer', models.TextField(verbose_name='réponse')),
                ('order', models.PositiveIntegerField(default=0, verbose_name="ordre d'affichage")),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='faqs', to='events.event', verbose_name='événement')),
            ],
            options={
                'verbose_name': 'question fréquente',
                'verbose_name_plural': 'questions fréquentes',
                'ordering': ['order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='EventGalleryItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(blank=True, help_text='Laisser vide pour une entrée de programme sans visuel.', null=True, upload_to='events/gallery/%Y/%m/', verbose_name='image')),
                ('title', models.CharField(blank=True, help_text="Légende de la photo, ou titre du passage (ex: 'Concert live').", max_length=200, verbose_name='titre')),
                ('subtitle', models.CharField(blank=True, help_text="Ex: nom de l'artiste/intervenant pour une entrée de programme.", max_length=200, verbose_name='sous-titre')),
                ('time', models.TimeField(blank=True, help_text='Renseigné uniquement pour une entrée de programme (ex: 20h00).', null=True, verbose_name='heure')),
                ('order', models.PositiveIntegerField(default=0, verbose_name="ordre d'affichage")),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gallery_items', to='events.event', verbose_name='événement')),
            ],
            options={
                'verbose_name': 'élément galerie / programme',
                'verbose_name_plural': 'galerie / programme',
                'ordering': ['order', 'time', 'id'],
            },
        ),
        migrations.CreateModel(
            name='EventPartner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150, verbose_name='nom')),
                ('logo', models.ImageField(blank=True, null=True, upload_to='events/partners/%Y/%m/', verbose_name='logo')),
                ('website_url', models.URLField(blank=True, verbose_name='site web')),
                ('order', models.PositiveIntegerField(default=0, verbose_name="ordre d'affichage")),
                ('event', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='partners', to='events.event', verbose_name='événement')),
            ],
            options={
                'verbose_name': 'partenaire',
                'verbose_name_plural': 'partenaires',
                'ordering': ['order', 'id'],
            },
        ),
    ]
