# IvoirPass V2 — État du projet

## Statut chantier (2026-09-25)
✅ **Toutes les tâches terminées, mergées en preprod.**
**Branche :** preprod-corrections-audit (commit 44b0f8c)
**Tag rollback :** preprod-avant-chantier-6 → f7cca51

## Tâches livrées
| # | Tâche | Statut |
|---|-------|--------|
| 1 | Lien d'accès en ligne (guest) | ✅ |
| 2 | Message KYC persistant | ✅ |
| 3 | InfoLine (ex-Description courte) | ✅ |
| 4 | Retrait sale_start/sale_end du formulaire | ✅ |
| 5 | Carrousel ~60vh desktop | ✅ |
| 6 | Retrait logique événement gratuit | ✅ |
| Bonus | Fix is_on_sale (vente jusqu'à fin) + garde-fou | ✅ |
| Bonus | Fix tests store (is_digital, stock, seller) | ✅ |
| Bonus | Config Celery (dev local) | ✅ |

## Décisions verrouillées
- InfoLine : label + help "Numéro de contact de l'organisateur"
- KYC : obligatoire pour publier (pas de distinction gratuit/payant)
- Prix minimum : 100 FCFA (MinValueValidator)
- Vente : jusqu'à end_date de l'événement
- Événements online : URL interne `/billets/live/<token>/` qui redirige vers Zoom

## En attente (à valider en preprod)
- [ ] Test KYC (organisateur non vérifié → message persistant)
- [ ] Test achat guest physique (email + QR + PDF)
- [ ] Test achat guest online (email avec lien /live/)
- [ ] Surveiller Sentry 24-48h
- [ ] Merge preprod → master → déploiement prod

## Leçons apprises
- **Docker :** toujours `docker compose build` (sans argument) + `up -d --force-recreate`.
  Ne JAMAIS faire `build web` seul — celery/beat gardent l'ancienne image.
- **Ne JAMAIS supprimer un Event qui a des commandes PAID** (cascade → perte de traçabilité BCEAO).
- **Migrations destructives :** vérifier en preprod avant prod.

## Commandes utiles
- Lancer en local : `./run_dev.sh` (Redis doit tourner)
- Tests ciblés : `DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.xxx`
- Redis local : `redis-server --daemonize yes`

## Historique
- 2026-09-25 : Session unique (longue) — 6 tâches + 3 bonus livrées, mergées, déployées preprod