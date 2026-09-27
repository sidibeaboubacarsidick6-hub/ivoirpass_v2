# 07 — Changelog

**Historique des chantiers et corrections.**
Public cible : maintenance, product, audit.

---

## Format

Chaque entrée liste :
- **Date** de clôture
- **Branche** et **tag rollback** si applicable
- **Commits** (hash + message)
- **Décisions verrouillées**
- **Leçons apprises** éventuelles

---

## 2026-09-27 — Chantier Boutique + Audit UI + Scanner Offline

**Branche** : `preprod-corrections-audit`
**Tags rollback** :
- `preprod-avant-chantier-boutique` (f7cca51) — avant boutique
- `preprod-avant-chantier-6` (f7cca51) — avant tickets (2026-09-25)

### Chantier C — Retirer PayDunya du frontend

**Commit** : `b52e3e1`

- Retrait des mentions "PayDunya" sur les pages acheteurs (billetterie + boutique)
- Conservé dans le dashboard admin (support) et les logs serveur

**Fichiers** : `templates/store/detail.html`, `templates/store/guest_checkout.html`, `templates/tickets/guest_checkout.html`

---

### Chantier A — Annulation événement (organisateur seul responsable)

**Commit** : `f2782c7` + UI `621afa2`

**Nouvelle logique métier** (décisions verrouillées) :
- IvoirPass **n'est PAS responsable** du remboursement
- L'organisateur gère directement auprès des acheteurs
- Le wallet organisateur est **gelé** si au moins 1 vente
- Aucun débit/crédit automatique
- Billets `void` → scanner refuse
- Commandes `CANCELLED` (jamais `REFUNDED`)

**Nouveau service** : `cancel_event_organizer_liable()` dans `apps/events/services.py`

**Migration** : `dashboard.0013` → `OrganizerWallet.is_frozen` + `frozen_reason`

**Templates créés** :
- `event_cancelled_buyer.{html,txt}` (email acheteur)
- `admin_event_cancelled.{html,txt}` (alerte admins)

**UI** : bouton adaptatif dans `my_events.html` :
- Événement avec ventes → 🚫 "Annuler l'événement"
- Événement sans ventes → 🗑️ "Supprimer"

**Retiré** : lien "Annuler" du formulaire de création d'événement

**Tests** : 8 cas (`tests/test_events_cancel_step_A.py`)

---

### Chantier B — Scanner PWA offline

**Commits** : `4436068` (B-1) → `aa7a0eb` (B-7) + fix `eccdf6a`

**7 sous-étapes livrées** :

| # | Contenu |
|---|---|
| B-1 | Service Worker + Manifest PWA + lib `html5-qrcode` en local |
| B-2 | API offline : `prepare_event_offline`, `sync_offline_scans` + refactor `_process_scan` |
| B-3 | Wrapper IndexedDB (2 stores : tickets, scan_queue) |
| B-4 | Écran "Préparer l'événement pour offline" |
| B-5 | Scan cache-first + fallback API |
| B-6 | Sync auto (event `online` + après scan + manuel) |
| B-7 | Tests serveur (7 cas) |

**Migration** : `scanner.0002` → `ScanLog.client_uuid` (idempotence sync)

**Nouvelles routes** :
- `POST /api/scanner/prepare/<event_id>/`
- `POST /api/scanner/sync/`
- `GET /scanner/app/sw.js`
- `GET /scanner/app/manifest.json`

**Décisions verrouillées** :
- Cache-first (pas online-first)
- Fallback API en ligne si billet non caché
- Pas de vérif HMAC côté client (revérification au sync serveur)
- Stockage IndexedDB en clair + purge à la déconnexion
- Batches de 100 scans par sync
- Le scan n'est PAS bloqué pendant une sync

**Fichiers clés** :
- `static/scanner-app/sw.js` (Service Worker)
- `static/scanner-app/manifest.json`
- `static/scanner-app/html5-qrcode.min.js` (lib locale, plus de CDN)
- `static/scanner-app/icon-192.svg`, `icon-512.svg`
- `templates/scanner_app/index.html` (refonte complète offline)

**Leçons apprises** :
- ⚠️ **`collectstatic` obligatoire** sur la VPS après ajout dans `static/` → sinon 404
- ⚠️ **Bump `CACHE_NAME`** dans `sw.js` après modif de `index.html` → sinon les mobiles gardent l'ancienne version pendant des jours
- Le SW ne s'enregistre qu'en HTTPS **ou** sur `localhost`
- L'emoji dans un SVG base64 casse le rendu navigateur → utiliser des vrais fichiers SVG

---

### Correctifs préprod (même session)

| Commit | Fix |
|---|---|
| `289da83` | Extensions Django **sans point** (`FileExtensionValidator(['png'])` au lieu de `['.png']`) — bug silencieux qui refusait **tous** les uploads |
| `0f9d617` | `product_create` ne retournait rien sur GET → 500 |
| `d252cc0` | `product_delete` (écrasé par un doublon `product_edit`) |
| `d25ecf0` | `icon-512.svg` déplacé au bon dossier |
| `eccdf6a` | SW bump v1 → v2 (purge 404) |

---

### Documentation créée

**Commit** : (à venir, ce doc)

- `docs/README.md` — index
- `docs/01-architecture.md`
- `docs/02-modele-donnees.md`
- `docs/03-flux-metier.md`
- `docs/04-securite.md`
- `docs/05-deploiement.md`
- `docs/06-api.md`
- `docs/07-changelog.md`
- `docs/08-cahier-des-charges-v2.md` (client)

**Fichier** : `PROJECT_STATE.md` mis à jour avec récap chantier.

---

## 2026-09-25 — Chantier Tickets (6 tâches)

**Branche** : `preprod-corrections-audit`
**Tag rollback** : `preprod-avant-chantier-6` (f7cca51)

### Tâches livrées

| # | Tâche |
|---|---|
| 1 | Lien d'accès en ligne (guest) — URL interne `/billets/live/<token>/` |
| 2 | Message KYC persistant avec instructions CNI |
| 3 | InfoLine (ex-"Description courte") — label + help |
| 4 | Retrait `sale_start` / `sale_end` du formulaire |
| 5 | Carrousel ~60vh sur desktop |
| 6 | Retrait de la logique "événement gratuit" |

**Bonus** :
- Fix `is_on_sale` (vente jusqu'à la fin de l'événement)
- Fix tests store (is_digital, stock, seller)
- Config Celery pour dev local

**Migrations** : `events.0007-0009`

**Leçons apprises** :
- 🚨 **`docker compose build web` seul = piège** → Celery/Beat gardent l'ancienne image. Toujours `build` sans argument + `up -d --force-recreate`.
- 🏛️ **Ne JAMAIS supprimer un `Event` avec commandes PAID** (cascade → perte traçabilité BCEAO)
- ✅ Vérifier migrations destructives en preprod avant prod

---

## 2026-09 — Audit initial (phase 0 à 2)

**Branches** : `fix/audit-phase0-securisation`, `fix/audit-corrections-phase1`, `fix/audit-phase2-phase4`

### Corrections structurelles

- Sécurisation des webhooks (vérification signature)
- Cloisonnement agents scanner (accès limité aux événements assignés)
- Vérification email obligatoire (`ACCOUNT_EMAIL_VERIFICATION='mandatory'`)
- Sécurité paiement (fix `payment-security-*`)
- Réconciliation paiement + alerte boutique
- Protection anti-double-scan (`select_for_update`)
- Fix bug critique annulation commande invité
- Fix conflit paiement/stock

**Commits clés** :
- `56f413c` — Backup avant corrections paiement (faille financière)
- `e2fda28` — Correctifs audit : libération stock, conflit paiement/stock, code mort

---

## 2026-06 — Version 2 initiale

**Commit** : `a4230b1` (branche `master`)

- Refonte v2 : dépendances à jour
- Sauvegardes auto
- Accessibilité
- Documentation API (drf-spectacular)
- Assignation scanner
- Couverture tests

---

## Chantiers reportés (backlog)

| Chantier | Priorité | Statut |
|---|---|---|
| **Drop `ProductOrder` + `DownloadLink`** | Moyenne | ⏭️ Reporté — nécessite réécriture back-office + BCEAO + factures |
| **Watermark MP3** | Basse | ⏭️ Reporté — complexité ré-encodage ID3 |
| **App mobile native (iOS/Android)** | Haute | ⏭️ Non démarré |
| **Chiffrement IndexedDB scanner** | Basse | ⏭️ Reporté — stockage clair suffisant en v1 |
| **Cagnottes / Cotisations** | Haute | ⏭️ Spécifié, non développé |
| **Points de vente physiques** | Moyenne | ⏭️ Backlog v2.1 |
| **WhatsApp Business API** | Moyenne | ⏭️ Backlog v2.1 |
| **Plan de salle interactif** | Basse | ⏭️ Backlog v2.2 |
| **Multi-pays** | Basse | ⏭️ Backlog v2.2 |

---

## Statistiques

### Tests

| Date | Total | OK | Skipped |
|---|---|---|---|
| 2026-09-25 | 198 | 196 | 2 |
| 2026-09-27 (matin) | 221 | 219 | 2 |
| 2026-09-27 (après B) | 236 | 234 | 2 |

### Migrations

| App | Dernière migration |
|---|---|
| accounts | `0007_add_managed_by_to_customuser` |
| events | `0009_remove_event_is_free_alter_tickettype_price` |
| tickets | `0005_guestticket_online_access_token` |
| store | `0013_alter_product_cover_image_alter_product_digital_file_and_more` |
| dashboard | `0013_organizerwallet_frozen_reason_and_more` |
| scanner | `0002_scanlog_client_uuid` |
| payments | `0004_add_store_order_fks_to_payment` |

---

## 📅 Dernière mise à jour

2026-09-27 — Documentation initiale.