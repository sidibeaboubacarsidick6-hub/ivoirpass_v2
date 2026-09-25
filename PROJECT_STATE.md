# IvoirPass V2 — État du projet

## Chantier en cours
**Branche :** preprod-corrections-audit
**Objectif :** 6 modifications événements (prompt du 2026-09-25)

## Tâches
| # | Tâche | Priorité | Statut |
|---|-------|----------|--------|
| 1 | Lien de connexion pour événements en ligne (au lieu du ticket) | Haute | ⏳ à faire |
| 2 | Message KYC visible plus longtemps avec instructions complètes | Haute | 🟡 email fait, UI à faire |
| 3 | "Description courte" → "InfoLine" | Moyenne | ✅ fait |
| 4 | Supprimer "Date de début" / "Date de fin" dans Dates et horaires | Moyenne | ⏳ à faire |
| 5 | Carrousel agrandi à 50% de l'écran | Moyenne | ⏳ à faire |
| 6 | Retirer la logique d'événement gratuit | Haute | ⏳ à faire |

## Décisions prises
- Help text InfoLine : "Numéro de contact de l'organisateur"
- Label : "InfoLine" (casse exacte)
- Périmètre InfoLine : événements uniquement (pas store)
- Email KYC : version validée le 2026-09-25

## Environnement
- Local : WSL Ubuntu + venv + PostgreSQL natif + Redis natif
- Lancement : ./run_dev.sh (runserver + celery + beat)
- Preprod : VPS, docker-compose.preprod.yml
- Settings local : config.settings.development

## Points de vigilance
- ALERTE SÉCURITÉ : Sentry DSN exposé le 2026-09-25 → à révoquer
- ALERTE SÉCURITÉ : ngrok PAYDUNYA_BASE_URL exposé → tunnel à fermer
- Le working tree reste sale tant qu'on n'a pas commité le chantier InfoLine/email

## Historique des sessions
- 2026-09-25 : Session 1 — cadrage, InfoLine, email KYC, push à venir