#!/bin/bash
# ============================================================
# IvoirPass V2 — Lancement complet en local (sans Docker)
#
# Démarre les 3 processus nécessaires pour que TOUT fonctionne
# (y compris les emails, qui passent par Celery) :
#   1. Le serveur Django (manage.py runserver)
#   2. Le worker Celery (exécute les tâches : emails, billets...)
#   3. Celery beat (déclenche les tâches planifiées : reversements, BCEAO)
#
# Usage :
#   chmod +x run_dev.sh   (une seule fois)
#   ./run_dev.sh
#
# Arrête tout proprement avec Ctrl+C.
# ============================================================

set -e

# Nettoyage : si on arrête ce script, on tue aussi les sous-processus
trap 'echo ""; echo "Arrêt de tous les processus..."; kill $(jobs -p) 2>/dev/null; exit' INT TERM

echo "============================================================"
echo "  Démarrage d'IvoirPass V2 (serveur + worker + planificateur)"
echo "============================================================"

echo "→ Démarrage du serveur Django..."
python manage.py runserver 0.0.0.0:8000 &

echo "→ Démarrage du worker Celery (emails, billets, notifications)..."
celery -A config worker --loglevel=info &

echo "→ Démarrage de Celery beat (tâches planifiées : reversements, BCEAO)..."
celery -A config beat --loglevel=info &

echo ""
echo "✅ Les 3 processus tournent. Ctrl+C pour tout arrêter proprement."
echo ""

# Attend que l'un des processus s'arrête (ou Ctrl+C)
wait