# 🎯 IvoirPass V2 — État du projet

**Dernière mise à jour :** 2026-10-07 (soir)
**Repo GitHub :** https://github.com/sidibeaboubacarsidick6-hub/ivoirpass_v2
**Branche de travail :** master

---

## 🎯 Le projet en 3 lignes

**IvoirPass** = plateforme de billetterie événementielle + boutique en Côte d'Ivoire.
- **Stack :** Django 4.2 + DRF + PostgreSQL 15 + Redis + Celery + Docker + Nginx
- **Prod (MKS Soft Technologies) :** prête à être lancée
- **Preprod :** prepod.ivoirpass.com (5 containers Docker)

**Utilisateur :** Sidibe (dev solo)
**Assistant :** Claude / DeepSeek
**Style :** français, tutoiement, commandes copiables, étape par étape

---

## ✅ Chantiers terminés

### Vagues initiales (avant 2026-10-06)
- **Vague 1** — Bugs + UI (emails, CA boutique, sold_count, cartes billets)
- **Vague 2** — Vidéo (mp4 100 Mo) + codes gratuits nominatifs
- **Vague 3.1** — Wallet divisé (events / store) + source sur transactions
- **Vague 4** — Multi-jours (EventDay, tunnel 3 étapes, scanner 1 scan/jour)

### Améliorations 2026-10-02
- 6 améliorations tunnel multi-jours
- 3 fixes sécurité paiement
- Politique de confidentialité (Loi 2013-450)
- Fix OTP `secrets` (au lieu de `random`)
- **Fix CRITIQUE Celery** (4 tâches `tasks.py` cassées → emails ne partaient pas)

### Session 2026-10-06 (soir) — Améliorations fonctionnelles
- ✅ Fix boutons retour tunnel multi-jours (lien GET au lieu de POST → plus d'erreurs)
- ✅ Script anti-perte de modifications (avant retour)
- ✅ Bloc "Lien scanner" dans `assign_scanner_agents.html` (avec WhatsApp + copie + ID événement)
- ✅ Revenus nets par produit (boutique) dans wallet — vue 2 colonnes
- ✅ Plafond retry `check_payout_status` (6h max anti-boucle Celery)
- ✅ Retrait mention "24-48h" du formulaire withdraw
- ✅ Quota codes gratuits : 20 → **10** par défaut
- ✅ Confirmation `payment_return` stricte (uniquement `status=completed`)
- ✅ Notification vendeur physique boutique (bug inversé corrigé)
- ✅ Commission figée sur `GuestOrder` (`default=0`)
- ✅ `dispatch_uid` sur signaux wallet
- ✅ SMS Orange (cache OAuth, early-return, troncature, normalisation)
- ✅ SMS boutique (legacy + invité)
- ✅ SMS annulation événement

### Session 2026-10-06 — Tests unitaires (gros chantier)
- ✅ **519 → 614 tests** (+95 tests)
- ✅ **Couverture : 39 % → 73 %** (+34 points)
- ✅ Fichiers critiques 85-97 % :
  - `tickets/views.py`, `store/watermark.py`, `core/tasks.py`
  - `payments/paydunya.py`, `dashboard/models.py`, `events/services.py`
  - `tickets/models.py`, `store/models.py`, `notifications/tasks.py`

### Session 2026-10-07 — Tests de charge (nouveau)
- ✅ Test **`ab`** (Apache Bench) sur 4 scénarios
- ✅ Test **Locust** (150 users simultanés, ~4 min, 6 742 requêtes)
- ✅ **0 erreur**, médiane 220 ms, 95e %ile 310 ms
- ✅ Preprod validée pour la prod

---

## 🚧 Backlog restant

### Priorité haute (avant prod)
- 🚀 **Bascule PayDunya en live** :
  - `PAYDUNYA_MODE=live` dans `.env`
  - Remplacer les 4 clés test par les clés live
  - Test à 100 FCFA réel sur les 4 opérateurs (Wave / OM / MTN / Moov)
  - **Vérifier que l'API PER est activée chez PayDunya** (décaissement auto)
- 🚀 **Clés Orange SMS** (attente retour supérieur)
  - `ORANGE_SMS_CLIENT_ID`, `ORANGE_SMS_CLIENT_SECRET`
  - `ORANGE_SMS_SENDER_ADDRESS`, `ORANGE_SMS_SENDER_NAME`
  - Puis `SMS_ENABLED=True` + restart
- 🚀 **Sentry prod** (vérifier DSN + test erreur 500 → alerte)
- 🚀 **Backup DB automatique** (cron VPS prod)
- 🚀 **SSL valide** + `DEBUG=False`

### Priorité moyenne (après lancement)
- Bug bouton hero (partie gauche) — ~30 min
- Doc PayDunya (`docs/09-providers-paiement.md`)
- Guide utilisateur `/comment-ca-marche/` (8 sections rédigées)
- Vague 3.2 — split multi-source reversement
- Vague 4 V2 — ré-entrée, remboursement jour annulé
- Jours sur les billets (PDF + confirmation + email)

### Améliorations optionnelles (après 500 users simultanés)
- Gunicorn : 3 → 5 workers
- Cache 5 min sur `event_detail` (visiteurs anonymes uniquement)
- Read-replica DB si > 10 000 scans/jour

---

## 🚀 Workflow déploiement (⚠️ CRITIQUE)

**TOUJOURS ces 4 étapes :**

```bash
# Local
git status
git add ...
git commit -m "..."
git push origin master

# VPS
cd ~/apps/preprod-ivoirpass
git pull origin master
docker compose -f docker-compose.preprod.yml build         # OBLIGATOIRE
docker compose -f docker-compose.preprod.yml up -d --force-recreate

# Vérifier les 5 containers
docker compose -f docker-compose.preprod.yml ps

# Si migration :
docker compose -f docker-compose.preprod.yml exec web python manage.py migrate

# Si CSS/JS :
docker compose -f docker-compose.preprod.yml exec web python manage.py collectstatic --noinput
📌 Leçons apprises
Toujours git status avant git add (fichiers oubliés)

Toujours build avant up -d --force-recreate

Jamais A || B dans les commandes git

Vérifier ps après déploiement (si Restarting → logs)

Tests locaux avant push

secrets (pas random) pour tokens/OTP

Mode test PayDunya protégé en prod

Patch avec import local : patcher à la source

Celery retry : assertRaises((Retry, ExceptionOriginale))

🔑 Config VPS
Hôte : vps-c9d8fab5 — 4 vCPU / 7,6 GB RAM

App preprod : ~/apps/preprod-ivoirpass

Domaine : prepod.ivoirpass.com

Containers : web, celery, celery-beat, db, redis

Gunicorn : 3 workers (à passer à 5 en prod)

Nginx : /etc/nginx/sites-enabled/prepod-ivoirpass

client_max_body_size 110M

Attention : le VPS héberge d'autres apps (az_app, intranet_app)

🧪 Tests & Coverage
Suite unitaire :

bash
DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests -v 1
→ 614 tests OK (2 skipped), ~12 s

Couverture :

bash
coverage run --source='apps' manage.py test tests
coverage report --skip-covered --sort=cover | tail -30
→ TOTAL ~73 %

Tests de charge (Locust) :

bash
locust -f tests/load/locustfile.py --host=https://prepod.ivoirpass.com
→ Voir rapport dédié docs/rapport-tests-charge.md

📞 Contacts
MKS Soft Technologies (éditeur)

Email : infos@mks-soft-technologies.com

Tél : (+225) 07 59 87 21 61 / 05 84 04 49 39

Utilisateur principal : Sidibe (sidibeaboubacarsidick6@gmail.com)