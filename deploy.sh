#!/bin/bash
#
# deploy.sh — Script de déploiement IvoirPass preprod
#
# Usage :
#   ./deploy.sh              # Déploiement complet
#   ./deploy.sh --no-build   # Sans rebuild (code Python uniquement)
#   ./deploy.sh --logs       # Affiche les logs en continu après déploiement
#
# À exécuter depuis ~/apps/preprod-ivoirpass après un git push.
#
set -euo pipefail

# ───────────────────────────────────────────────────────────
# CONFIGURATION
# ───────────────────────────────────────────────────────────
APP_DIR="$HOME/apps/preprod-ivoirpass"
COMPOSE_FILE="docker-compose.preprod.yml"
SERVICES_TO_BUILD=("web" "celery" "celery-beat")
GIT_BRANCH="master"

# Options
SKIP_BUILD=0
FOLLOW_LOGS=0
for arg in "$@"; do
  case "$arg" in
    --no-build) SKIP_BUILD=1 ;;
    --logs)     FOLLOW_LOGS=1 ;;
  esac
done

# ───────────────────────────────────────────────────────────
# COULEURS
# ───────────────────────────────────────────────────────────
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
BLUE="\033[0;34m"
NC="\033[0m" # No Color

log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail() { echo -e "${RED}❌ $*${NC}"; }

# ───────────────────────────────────────────────────────────
# ÉTAPE 0 — Vérifications préalables
# ───────────────────────────────────────────────────────────
cd "$APP_DIR" || { fail "Impossible d'accéder à $APP_DIR"; exit 1; }

log "Déploiement IvoirPass preprod"
log "  Dossier : $APP_DIR"
log "  Branche : $GIT_BRANCH"
echo

# Vérifier que git n'a pas de modifications locales non commitées
if ! git diff --quiet || ! git diff --cached --quiet; then
  warn "Modifications locales détectées dans le repo."
  warn "Ces modifs seront perdues si elles ne sont pas commitées."
  echo
  git status -sb
  echo
  read -p "Continuer quand même ? (y/N) " -r
  if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    fail "Déploiement annulé."
    exit 1
  fi
fi

# ───────────────────────────────────────────────────────────
# ÉTAPE 1 — Git pull
# ───────────────────────────────────────────────────────────
log "1/7 — Récupération des dernières modifications..."
BEFORE_COMMIT=$(git rev-parse --short HEAD)
git pull origin "$GIT_BRANCH"
AFTER_COMMIT=$(git rev-parse --short HEAD)

if [ "$BEFORE_COMMIT" = "$AFTER_COMMIT" ]; then
  warn "Aucune nouvelle modification (HEAD = $AFTER_COMMIT)"
else
  ok "Mise à jour : $BEFORE_COMMIT → $AFTER_COMMIT"
fi
echo

# ───────────────────────────────────────────────────────────
# ÉTAPE 2 — Build des images
# ───────────────────────────────────────────────────────────
if [ "$SKIP_BUILD" -eq 1 ]; then
  warn "2/7 — Build ignoré (--no-build)"
else
  log "2/7 — Build des images Docker..."
  docker compose -f "$COMPOSE_FILE" build "${SERVICES_TO_BUILD[@]}"
  ok "Build terminé"
fi
echo

# ───────────────────────────────────────────────────────────
# ÉTAPE 3 — Recréation des containers
# ───────────────────────────────────────────────────────────
log "3/7 — Recréation des containers..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate
ok "Containers recréés"
echo

# ───────────────────────────────────────────────────────────
# ÉTAPE 4 — Migrations
# ───────────────────────────────────────────────────────────
log "4/7 — Application des migrations..."
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py migrate
ok "Migrations OK"
echo

# ───────────────────────────────────────────────────────────
# ÉTAPE 5 — Collecte des fichiers statiques
# ───────────────────────────────────────────────────────────
log "5/7 — Collecte des fichiers statiques (avec --clear)..."
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py collectstatic --clear --noinput
ok "Fichiers statiques collectés"
echo

# ───────────────────────────────────────────────────────────
# ÉTAPE 6 — Reload Nginx
# ───────────────────────────────────────────────────────────
log "6/7 — Rechargement Nginx..."
if sudo -n /usr/sbin/nginx -t 2>/dev/null; then
  sudo -n /usr/bin/systemctl reload nginx 2>/dev/null && ok "Nginx rechargé" || warn "Nginx reload échoué (peut-être pas nécessaire)"
else
  warn "Test Nginx impossible (droits sudo ?) — étape ignorée"
fi
echo

# ─── Nettoyage Docker (garde 7j de build cache, 14j d'images) ───
# Empêche le disque de se remplir à chaque déploiement.
# Les images des containers ACTIFS sont toujours préservées.
docker builder prune -af --filter "until=168h"  > /dev/null 2>&1 || true
docker image prune -af --filter "until=336h"    > /dev/null 2>&1 || true


# ───────────────────────────────────────────────────────────
# ÉTAPE 7 — Vérifications finales
# ───────────────────────────────────────────────────────────
log "7/7 — Vérifications finales..."
echo
docker compose -f "$COMPOSE_FILE" ps

echo
log "Logs des 10 dernières secondes (web + celery) :"
docker compose -f "$COMPOSE_FILE" logs --since 10s web celery celery-beat 2>&1 \
  | grep -iE "error|traceback|exception" \
  | grep -v "PAYDUNYA_MODE" \
  | head -10 \
  || true

echo
ok "Déploiement terminé (commit : $AFTER_COMMIT)"
echo

# ───────────────────────────────────────────────────────────
# BONUS — Suivre les logs
# ───────────────────────────────────────────────────────────
if [ "$FOLLOW_LOGS" -eq 1 ]; then
  log "Suivi des logs (Ctrl+C pour quitter)..."
  echo
  docker compose -f "$COMPOSE_FILE" logs -f web celery celery-beat
fi
