# 05 — Déploiement

**Docker, migrations, statiques, Service Worker, Celery.**
Public cible : devops, dev back-end.

---

## 1. Environnements

| Env | Config Django | Base | Cache | Usage |
|---|---|---|---|---|
| **dev** | `development.py` | PostgreSQL (ou SQLite) | Redis local | Développement |
| **testlocal** | `testlocal.py` | SQLite mémoire | Aucun | Tests unitaires |
| **preprod** | `production.py` | PostgreSQL Docker | Redis Docker | Validation |
| **prod** | `production.py` | PostgreSQL VPS | Redis VPS | Production |

---

## 2. Développement local

### 2.1 Script de lancement

```bash
./run_dev.sh
Lance 3 processus : Django runserver + Celery worker + Celery beat.

Prérequis : Redis doit tourner (redis-server --daemonize yes).

2.2 Alternative manuelle
bash
python manage.py runserver
celery -A config worker -l info         # dans un autre terminal
celery -A config beat -l info           # dans un 3e terminal
2.3 Tunnel public (webhooks PayDunya)
bash
ngrok http 8000
Un seul tunnel suffit — le site et le scanner PWA sont servis par le même serveur.

Mettre à jour PAYDUNYA_BASE_URL dans .env avec l'URL ngrok.

3. Docker preprod / prod
3.1 Services
docker-compose.preprod.yml contient 5 services :

Service	Rôle	Port
db	PostgreSQL 15	non exposé
redis	Redis 7	non exposé
web	Gunicorn + Django	127.0.0.1:8100 (localhost uniquement)
celery	Worker Celery	interne
celery-beat	Planificateur	interne
Sécurité réseau : DB et Redis non publiés à l'extérieur. Web exposé uniquement sur localhost — Nginx proxy vers ce port.

3.2 Variables d'environnement
Fichier .env.preprod (ou .env) avec :

SECRET_KEY, DEBUG=False, ALLOWED_HOSTS

DB_*, DB_PASSWORD

REDIS_URL, CELERY_BROKER_URL

PAYDUNYA_* (mode test/live)

EMAIL_*, ADMIN_EMAIL

Jamais commité (vérifié CI).

4. Procédure de déploiement standard
4.1 Sur le serveur
bash
cd ~/apps/preprod-ivoirpass
git pull origin preprod-corrections-audit       # ou master en prod
docker compose -f docker-compose.preprod.yml build
docker compose -f docker-compose.preprod.yml up -d --force-recreate
docker compose -f docker-compose.preprod.yml exec web python manage.py migrate
docker compose -f docker-compose.preprod.yml exec web python manage.py collectstatic --noinput
docker compose -f docker-compose.preprod.yml ps
docker compose -f docker-compose.preprod.yml logs --tail=50 web
4.2 ⚠️ Règle du rebuild
Toujours docker compose build SANS argument + up -d --force-recreate.

Ne JAMAIS faire docker compose build web seul → Celery et Beat gardent l'ancienne image (ils ne verraient pas les nouveaux tasks.py).

4.3 Ordre des opérations
git pull

build (sans argument)

up -d --force-recreate (recrée tous les containers)

migrate (application des migrations)

collectstatic (si des fichiers static/ ont changé)

Vérifications (ps, logs)

5. Migrations
5.1 En local
bash
python manage.py makemigrations <app>
python manage.py migrate <app>
5.2 En preprod/prod
bash
docker compose -f docker-compose.preprod.yml exec web python manage.py migrate
5.3 Migrations destructives
Vérification obligatoire en preprod avant prod :

bash
docker compose -f docker-compose.preprod.yml exec web python manage.py showmigrations <app>
Si une migration supprime une table ou une colonne :

Vérifier qu'aucune donnée n'est perdue (SELECT COUNT(*) avant)

Backup DB préalable

Créer un tag rollback Git

5.4 Migrations « state-only »
Certaines migrations (alter validators, help_text, labels) n'ont aucun impact SQL. Vérifier avec :

bash
python manage.py sqlmigrate <app> <numéro>
Si la sortie est vide → c'est du state-only, aucun risque.

6. Fichiers statiques
6.1 ⚠️ collectstatic obligatoire
Après chaque ajout ou modification dans static/ :

bash
docker compose -f docker-compose.preprod.yml exec web python manage.py collectstatic --noinput
Sinon les nouveaux fichiers retournent 404 (Nginx les sert depuis /app/staticfiles/).

6.2 Vérification
bash
curl -I https://prepod.ivoirpass.com/static/scanner-app/html5-qrcode.min.js
Attendu : HTTP/2 200.

6.3 Nginx
Nginx sert /static/ directement depuis le volume partagé. Pas de config supplémentaire à faire après collectstatic — la modification est immédiate.

7. Service Worker (Scanner PWA)
7.1 ⚠️ Bump CACHE_NAME à chaque changement d'index.html
Si templates/scanner_app/index.html change :

Dans static/scanner-app/sw.js, modifier :

javascript
const CACHE_NAME = 'ivoirpass-scanner-v2';   // v2 → v3 → v4...
Pourquoi : sans bump, les mobiles gardent l'ancienne version du HTML/JS pendant des jours (le SW sert l'ancien cache en priorité).

7.2 Séquence
bash
# En local
# 1. Modifier index.html
# 2. Bumper CACHE_NAME dans sw.js
git add static/scanner-app/sw.js templates/scanner_app/index.html
git commit -m "feat(scanner): ..."
git push origin preprod-corrections-audit

# Sur la VPS
git pull
docker compose build
docker compose up -d --force-recreate
docker compose exec web python manage.py collectstatic --noinput
7.3 Forcer la mise à jour côté mobile
Après déploiement, les mobiles déjà installés doivent :

Soit attendre la prochaine visite (le SW se réinstalle automatiquement avec la nouvelle version)

Soit forcer manuellement (Chrome : chrome://serviceworker-internals/ → Unregister)

8. Celery & Celery Beat
8.1 Où ça tourne
Worker Celery : emails, PDF, réconciliation, alertes admin

Celery Beat : planificateur (reconcil, reversements auto)

Les deux sont dans des containers séparés (voir docker-compose.preprod.yml).

8.2 ⚠️ Rebuild obligatoire si tasks.py change
Toute modification dans :

apps/*/tasks.py

apps/notifications/*

apps/payments/tasks.py

→ nécessite rebuild complet :

bash
docker compose build              # ← sans argument
docker compose up -d --force-recreate
Sinon Celery garde l'ancien code.

8.3 Vérifier que les tâches passent
bash
docker compose exec celery celery -A config inspect active
docker compose logs --tail=50 celery
docker compose logs --tail=50 celery-beat
9. Sauvegardes
9.1 Base de données
bash
docker compose exec db pg_dump -U ivoirpass_preprod_user ivoirpass_preprod_db > backup_$(date +%Y%m%d).sql
9.2 Retention
La tâche Celery backup_retention purge les backups > 30 jours (cf. tests/test_backup_retention_audit.py).

9.3 Media
Volume Docker ./media:/app/media — à sauvegarder séparément (rsync, snapshot VPS).

10. Rollback
10.1 Rollback code
Un tag Git de rollback doit être créé avant chaque chantier risqué :

bash
git tag -a preprod-avant-chantier-<nom> -m "..."
git push origin preprod-avant-chantier-<nom>
En cas de problème :

bash
git checkout preprod-avant-chantier-<nom>
docker compose build && docker compose up -d --force-recreate
10.2 Rollback migration
Django permet de revenir en arrière :

bash
python manage.py migrate <app> <numéro_précédent>
Uniquement valide si la migration est réversible (pas de RunPython sans reverse).

10.3 Tags existants
Tag	Chantier
preprod-avant-chantier-6	Chantier tickets (2026-09-25)
preprod-avant-chantier-boutique	Chantier boutique (2026-09-27)
11. CI/CD
11.1 GitHub Actions
Fichier .github/workflows/*.yml :

À chaque push/PR :

Installe Python 3.12 + requirements

python manage.py migrate --noinput

python manage.py test tests -v 2

Vérifie qu'aucun .env ou .sql n'est dans l'historique

Settings CI : DJANGO_SETTINGS_MODULE=config.settings.testlocal (SQLite mémoire, aucune dépendance externe).

11.2 Pas de déploiement automatique
Le déploiement se fait manuellement sur le VPS (voir §4). Pas de CD automatique — décision pour garder le contrôle.

12. Commandes utiles
bash
# Voir l'état des containers
docker compose -f docker-compose.preprod.yml ps

# Logs d'un service
docker compose -f docker-compose.preprod.yml logs -f web
docker compose -f docker-compose.preprod.yml logs --tail=100 celery

# Entrer dans le container web
docker compose -f docker-compose.preprod.yml exec web bash

# Shell Django
docker compose -f docker-compose.preprod.yml exec web python manage.py shell

# Vérifier les migrations
docker compose -f docker-compose.preprod.yml exec web python manage.py showmigrations

# Vider Redis (⚠️ DEV uniquement)
docker compose -f docker-compose.preprod.yml exec redis redis-cli FLUSHALL
13. Points d'attention
🚨 À ne jamais faire
docker compose build web seul (Celery/Beat gardent l'ancien code)

docker compose down -v (supprime les volumes → perte DB + media)

Modifier .env.preprod sans redémarrer les services (up -d --force-recreate)

Oublier collectstatic après ajout de fichiers statiques

Oublier de bumper CACHE_NAME après modif de index.html (PWA)

⚠️ À vérifier à chaque déploiement
□ git pull fait sur la bonne branche
□ build sans argument
□ up -d --force-recreate
□ migrate (si migrations en attente)
□ collectstatic (si static modifié)
□ CACHE_NAME bumpé (si index.html modifié)
□ 5/5 containers UP
□ Logs web sans erreur
□ Sentry calme dans les 15 min qui suivent
