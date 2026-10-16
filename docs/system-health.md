markdown
# Santé système — IvoirPass V2

**Dernière mise à jour :** 2026-10-16

Ce document décrit les mécanismes de surveillance et de sauvegarde en place sur le VPS de preprod (`vps-c9d8fab5`).

---

## 🔄 Vue d'ensemble

| Mécanisme | Fréquence | Où | État |
|---|---|---|---|
| **Backup DB** (script VPS) | 2h00 tous les jours | `/home/ubuntu/backup-db.sh` | ✅ actif |
| **Backup média** (manuel) | ponctuel | `~/backups/` | ⏸️ manuel |
| **Renouvellement SSL** (certbot) | 3h00 lundi | crontab | ✅ actif |
| **Réconciliation PayDunya** | toutes les 20 min | Celery Beat | ✅ actif |
| **Libération stock** | toutes les 15 min | Celery Beat | ✅ actif |
| **Check retraits en attente** | 8h, 14h, 20h | Celery Beat | ✅ actif |
| **Rapport BCEAO** | 1er du mois, 8h | Celery Beat | ✅ actif |
| **Rapport hebdo** | Lundi 8h30 | Celery Beat | ✅ actif |
| **Dashboard technique** | à la demande | `/tech-<secret>/` | ✅ actif |

---

## 💾 Backups PostgreSQL

### Script `~/backup-db.sh`

**Emplacement :** `/home/ubuntu/backup-db.sh`
**Cron :** `0 2 * * * /home/ubuntu/backup-db.sh >> /home/ubuntu/backups/backup.log 2>&1`

**Ce qu'il fait (pour chaque DB) :**

1. **Dump** → `pg_dump` dans le container Docker
2. **Compression** → `gzip` (fichier `.sql.gz`)
3. **Vérification intégrité** → `gzip -t` + taille > 0
4. **Chiffrement** → `gpg --symmetric --cipher-algo AES256`
5. **Upload** → Backblaze B2 (`rclone`)
6. **Vérification cloud** → taille distante == taille locale
7. **Suppression locale du `.gpg`** (uploadé avec succès)
8. **Rotation** → suppression des `.gz` > 7 jours

**Bases sauvegardées :**

| Container | Base | User |
|---|---|---|
| `intranet_db_container` | `mks_base` | `mks` |
| `az_db_container` | `az_base` | `az` |
| `preprod-ivoirpass-db-1` | `ivoirpass_preprod_db` | `ivoirpass_preprod_user` |

**Destination cloud :**
- **Remote rclone :** `backblaze`
- **Bucket :** `ivoirpass-backups-sidibe`
- **Chemin :** `<bucket>/<db_name>/backup_<db_name>_<timestamp>.sql.gz.gpg`

**Fichiers locaux :**
- **Backups bruts (non chiffrés) :** `/home/ubuntu/backups/postgres/*.sql.gz`
- **Log :** `/home/ubuntu/backups/backup.log`

**Passphrase GPG :** `/home/ubuntu/.gpg-passphrase` (**chmod 600** — ne pas exposer)

### Restauration d'un backup

**1. Télécharger depuis Backblaze :**
```bash
rclone copy backblaze:ivoirpass-backups-sidibe/ivoirpass_preprod_db/backup_ivoirpass_preprod_db_YYYYMMDD_HHMMSS.sql.gz.gpg /tmp/
2. Déchiffrer :

bash
gpg --batch --yes --quiet \
    --decrypt \
    --passphrase-file /home/ubuntu/.gpg-passphrase \
    --output /tmp/backup.sql.gz \
    /tmp/backup_ivoirpass_preprod_db_*.sql.gz.gpg
3. Décompresser :

bash
gunzip /tmp/backup.sql.gz
4. Restaurer dans le container (⚠️ DESTRUCTIF) :

bash
cd ~/apps/preprod-ivoirpass
docker compose -f docker-compose.preprod.yml exec -T db \
  psql -U ivoirpass_preprod_user -d ivoirpass_preprod_db \
  < /tmp/backup.sql
⚠️ TOUJOURS faire un backup frais AVANT de restaurer.

🔐 SSL / HTTPS
Outil : certbot (Let's Encrypt)
Cron : 0 3 * * 1 (chaque lundi à 3h)

Ce qu'il fait :

Tente un renouvellement (si < 30 jours avant expiration)

Reload nginx automatiquement

Vérifier manuellement :

bash
sudo certbot certificates
Forcer un renouvellement :

bash
sudo docker run --rm \
  -v /var/www/certbot:/var/www/certbot \
  -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot renew --webroot -w /var/www/certbot
sudo systemctl reload nginx
⚙️ Tâches Celery Beat
Scheduler : django_celery_beat.schedulers:DatabaseScheduler
Config : config/settings/base.py::CELERY_BEAT_SCHEDULE

Nom	Fréquence	Rôle
check-pending-withdrawals	8h, 14h, 20h	Détecte retraits en attente
reconcile-pending-payments	*/20 min	Rattrape paiements PayDunya manqués par webhook
release-expired-pending-orders	*/15 min	Libère stock commandes abandonnées
release-expired-product-orders	*/15 min	Idem boutique
generate-bceao-report	1er du mois, 8h	Rapport BCEAO (obligation légale)
send-weekly-report	Lundi 8h30	Rapport hebdo par email
⚠️ Note historique : la tâche backup-database-nightly a été retirée le 2026-10-16 car redondante avec le script VPS (dump perdu dans le container à chaque rebuild).

## 📧 Rapport hebdomadaire (lundi 8h30)

**Tâche Celery :** `apps.dashboard.tasks.send_weekly_report`
**Planifié :** chaque lundi à 08h30 (timezone Africa/Abidjan)
**Module :** `apps/dashboard/reports.py`

### Ce qu'il envoie

- **Format :** Excel multi-onglets (`.xlsx`)
- **Protection :** ZIP chiffré par mot de passe (hors email)
- **Contenu :** ventes, litiges, wallet, activité (voir `build_weekly_report_zip()`)
- **Période :** les 7 derniers jours (lundi → dimanche)
- **Sujet :** `[IvoirPass] Rapport hebdomadaire — JJ/MM/AAAA → JJ/MM/AAAA`
- **Template :** `templates/notifications/email/weekly_report.html`

### Configuration (`~/apps/preprod-ivoirpass/.env`)

```bash
# Destinataires (séparés par virgule)
WEEKLY_REPORT_RECIPIENTS=dir@example.com,fin@example.com

# Mot de passe du ZIP (communiqué hors email aux destinataires)
WEEKLY_REPORT_ZIP_PASSWORD=<mot-de-passe-fort>

📊 Dashboard technique
URL secrète : /tech-<secret>/ (voir config/urls.py)
Accès : superuser uniquement

7 blocs :

Alertes — paiements échoués, notifications admin non lues

Confirmations — CA encaissé, users, events publiés, billets

Actions en attente — KYC, retraits, annulations

Santé système — DB, Redis, Celery Beat, migrations

Stats 7 jours — graphiques Chart.js (litiges, paiements, users)

Activité chatbot — questions, taux d'échec, top ratées

Litiges — top 10 à traiter

Logs ChatbotLog : /admin/chatbot/chatbotlog/ (lecture seule)

🚨 En cas d'incident
Backup échoué (log dit "ERREUR")
bash
# Vérifier le log complet
tail -50 ~/backups/backup.log

# Causes fréquentes :
# - Container DB arrêté → vérifier : docker ps
# - Espace disque plein → vérifier : df -h
# - rclone mal configuré → vérifier : rclone config
# - Passphrase GPG absente → vérifier : ls -la ~/.gpg-passphrase
Container restart en boucle
bash
cd ~/apps/preprod-ivoirpass
docker compose -f docker-compose.preprod.yml ps
docker compose -f docker-compose.preprod.yml logs --tail=50 web
Redis KO sur le dashboard
bash
docker compose -f docker-compose.preprod.yml restart redis
Migration bloquée
⚠️ Jamais --fake sans backup préalable.

bash
cd ~/apps/preprod-ivoirpass
docker compose -f docker-compose.preprod.yml exec web \
  python manage.py showmigrations
📁 Arborescence des fichiers critiques
text
/home/ubuntu/
├── backup-db.sh              ← Script backup (chmod +x, root:ubuntu)
├── .gpg-passphrase           ← Passphrase chiffrement (chmod 600)
└── backups/
    ├── backup.log            ← Log des backups quotidiens
    ├── postgres/             ← Backups bruts (7j rotation)
    │   ├── backup_mks_base_*.sql.gz
    │   ├── backup_az_base_*.sql.gz
    │   └── backup_ivoirpass_preprod_db_*.sql.gz
    └── *.tar.gz              ← Backups média ponctuels (manuels)

~/apps/preprod-ivoirpass/
├── deploy.sh                 ← Script de déploiement
├── docker-compose.preprod.yml
├── .env                      ← Secrets (ADMIN_URL, SECRET_KEY, PAYDUNYA_*, etc.)
└── apps/

~/ivoirpass/                  ← Repo local (dev)
└── config/
    ├── settings/base.py      ← CELERY_BEAT_SCHEDULE, INSTALLED_APPS, etc.
    └── urls.py               ← Routes principales, dont TECH_DASHBOARD_URL
🔑 Secrets à ne JAMAIS committer
.env (SECRET_KEY, PAYDUNYA_*, MISTRAL_API_KEY, etc.)

.gpg-passphrase

rclone.conf (~/.config/rclone/rclone.conf)

Tokens d'API (Sentry, Backblaze)

📞 Contacts
Éditeur : MKS Soft Technologies — Abidjan
Email support : infos@mks-soft-technologies.com
Email backup (copie) : ivoirpass@gmail.com
Dev principal : Sidibe Aboubacar — sidibeaboubacarsidick6@gmail.com

