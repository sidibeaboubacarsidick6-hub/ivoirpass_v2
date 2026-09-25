# IvoirPass V2 — État du projet

## Chantier en cours
**Branche :** preprod-corrections-audit
**Objectif :** 6 modifications événements (prompt du 2026-09-25)

## Tâches
| # | Tâche | Priorité | Statut |
|---|-------|----------|--------|
| 1 | Lien de connexion pour événements en ligne (au lieu du ticket) | Haute | ✅ fait |
| 2 | Message KYC visible plus longtemps avec instructions complètes | Haute | ✅ fait |
| 3 | "Description courte" → "InfoLine" | Moyenne | ✅ fait |
| 4 | Supprimer "Date de début" / "Date de fin" dans Dates et horaires | Moyenne | ✅ fait (sale_start/sale_end retirés) |
|| 5 | Carrousel agrandi à 50% de l'écran | Moyenne | ✅ fait |
| 6 | Retirer la logique d'événement gratuit | Haute | ✅ fait |

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
- 2026-09-25 : Session 1 — InfoLine ✅, Email KYC ✅, Message KYC persistant ✅ (commit 25ea5aa)
- 2026-09-25 : Session 2 — Tâche 1 terminée : lien d'accès en ligne (guest online_access_token), page /billets/live/<token>/, email guest online, retrait valid_date du formulaire
- 2026-09-25 : Session 3 — Tâche 5 terminée : carrousel hero agrandi (~60vh desktop, mobile inchangé)
- 2026-09-25 : Session 4 — Tâche 4 terminée : retrait de sale_start/sale_end du formulaire Event et TicketType (modèle inchangé, valeurs NULL → fallback automatique publication/date event)
- 2026-09-25 : Session 5 — Tâche 6 terminée : suppression de Event.is_free (migration), MinValueValidator(100) sur TicketType.price, nettoyage complet code + templates. Toutes les 6 tâches fermées ✅