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

## Chantier Boutique Culturelle — 2026-09-27

**Branche :** `preprod-corrections-audit`
**Tag rollback :** `preprod-avant-chantier-boutique`
**Statut :** déployé preprod, **pas encore mergé master** (en attente tests manuels + Sentry 24h)

### Tâches livrées

| # | Tâche | Statut |
|---|-------|--------|
| 1 | Validateurs d'upload (extensions + tailles) | ✅ |
| 2 | Lien d'album externe (`external_url` + compteur de clics) | ✅ |
| 3 | KYC obligatoire pour publier un produit | ✅ |
| 4 | Prix minimum 500 FCFA | ✅ |
| 5 | Renommer short_description → InfoLine | ✅ |
| 6 | Fix bundle stock=0 (numérique seul, physique bloqué) | ✅ |
| 7 | Fix CRITIQUE cancel/refund (stock jamais restauré) | ✅ |
| 8 | Fix `Product.is_physical` (propriété perdue en étape 1) | ✅ |
| 9 | Fix `ProductAdmin.actions` doublon | ✅ |
| 10 | Fix 500 `product_create` (return manquant sur GET) | ✅ |
| 11 | Fix `product_delete` (écrasé par doublon product_edit) | ✅ |
| 12 | Fix CRITIQUE `FileExtensionValidator` (extensions sans point) | ✅ |
| 13 | Bandeau erreurs dans `product_form.html` | ✅ |
| 14 | Watermark MP3 — documenté | ⏭️ Reporté |
| 15 | Suppression code mort ProductOrder / DownloadLink | ⏭️ **Reporté** |

### Décisions verrouillées

- **Prix min boutique** : 500 FCFA (vs tickets, 100 FCFA)
- **InfoLine** : label + help "Numéro de contact du propriétaire"
- **`external_url` prioritaire** si les deux (fichier + lien) renseignés
- **Compteur externe** ne consomme PAS la limite de downloads
- **KYC via `is_organizer_verified`** (BooleanField, pas `kyc_verified_at`) + `extra_tags='danger kyc-persistent'`
- **Bundle stock=0** → numérique vendable, physique bloqué avec message clair

### Reporté (chantier dédié futur)

- **Drop `ProductOrder` + `DownloadLink`** : modèles **LUS** activement par
  back-office financier, exports admin, rapport BCEAO, factures PDF, FK Payment.
  Suppression = réécriture complète des consommateurs + FK Payment +
  signaux dashboard.
  **Vérifié en preprod 2026-09-27** : 0 `ProductOrder`, 0 `DownloadLink`.
  → Non critique tant que 0 ligne.
  Commentaires `LEGACY` ajoutés dans `apps/store/models.py` pour guider le futur dev.
- **Watermark MP3** : non implémenté (complexité ré-encodage ID3).

### Leçons apprises (mises à jour 2026-09-27)

- **`FileExtensionValidator` Django attend des extensions SANS point** :
  Django fait `os.path.splitext(name)[1][1:]` avant comparaison.
  Passer `['.png']` → jamais matché. **Toujours** passer `['png']`.
  Aligner sur la convention déjà utilisée par KYC (`apps/accounts/models.py:159`).
- **Validators `@deconstructible` obligatoires** : un closure retourné par
  une factory ne se sérialise pas dans une migration →
  `ValueError: Could not find function` à `makemigrations`.
- **`is_organizer` et `is_organizer_verified`** : vérifier si ce sont des
  `@property` (calculées depuis `role`) ou des champs stockés avant de les
  utiliser dans un garde-fou. `is_organizer_verified` est un **BooleanField
  dédié**, pas dérivé de `kyc_verified_at`.
- **Tests : créer les `ProductCategory`** dans les fixtures de form
  (`category` est requis côté ModelForm même si `null=True` en base).
- **Toujours afficher `form.errors` dans les templates de form** : sinon
  l'utilisateur voit "Veuillez corriger les erreurs" sans savoir quoi.
  Bandeau ajouté dans `product_form.html`.
- **Tests d'upload** : appeler le **vrai** `FileExtensionValidator` de Django
  dans les tests, pas seulement nos wrappers custom — c'est ce qui aurait
  attrapé le bug d'extensions dès le début.

### Fixes correctifs préprod (à tracer)

- `0f9d617` — 500 `product_create` (return manquant sur GET) + `product_delete` restaure
- `289da83` — extensions sans point (Django) + bandeau erreurs form + logs serveur
## Dernière mise à jour — 2026-09-30

### ✅ Vagues terminées

#### Vague 1 — Fix bugs + UI (terminée 2026-09-29)
- Bug mail bundle (template selon `delivery_method`)
- Bug stats boutique dashboard (utilisait `ProductOrder` legacy → `GuestProductOrder`)
- `sold_count` incrémenté pour TOUTES les ventes (physiques + numériques)
- Label prix dynamique selon type produit (physical/digital/bundle)
- Refonte cartes de billets (minimaliste pro)
- Script rattrapage `recalc_sold_count` (appliqué preprod : 5 produits corrigés)

#### Vague 2 — Vidéo + Codes gratuits (terminée 2026-09-30)
**2.1 — Upload vidéo événement**
- Champ `video_file` (mp4, 100 Mo max) sur `Event`
- Propriété `video_embed_url` (conversion YouTube/Vimeo auto)
- Section vidéo sur la landing (HTML5 `<video>` ou `<iframe>` responsive)
- Fix nginx preprod `client_max_body_size 110M` (note dans `docs/vps/`)

**2.2 — Codes de billets gratuits**
- Modèle `FreeTicketCode` (`apps/tickets`) : code `FREE-XXXX-XXXX` unique
- `Event.free_tickets_quota` (défaut 20) + `free_tickets_generated`
- Vue organisateur : génération en masse (textarea nom + email), export CSV
- Vue publique `/evenements/<slug>/code-gratuit/` : réclamation par code
- Création auto d'une `GuestOrder` gratuite + `GuestTicket` + email
- Action admin bulk : augmenter le quota (traçabilité AuditLog)

#### Vague 3.1 — Wallet divisé (terminée 2026-09-30)
- `OrganizerWallet` : 4 nouveaux champs (`balance_events_available/pending`,
  `balance_store_available/pending`) + 2 propriétés calculées
  (`balance_available`, `balance_pending` = events + store)
- `WalletTransaction.source` : events / store / legacy
- `WithdrawalRequest.source` : events / store — choix au moment du reversement
- Migration `dashboard.0015_wallet_split` avec `RunPython` (historique
  attribué à Événements)
- Méthodes refactorées : `credit(source=)`, `reserve(source=)`,
  `release_reserved(source=)`, `complete_reserved(source=)`,
  `debit(source=)`, `refund_charge(source=)`
- **Impossible de piocher dans l'autre poche** (ValueError sinon)
- Admin : `WalletTransactionAdmin` créé, `OrganizerWalletAdmin` refondu
- Templates : 3 soldes affichés (Général / Événements / Boutique),
  radios de choix de source dans le formulaire de reversement

**Bonus Vague 3.1** — Action admin dégel wallet
- Action bulk `unfreeze_wallets` sur `OrganizerWalletAdmin`
- Form avec raison obligatoire + traçabilité AuditLog (`WALLET_UNFROZEN`)
- Utile quand un wallet a été gelé par `cancel_event_organizer_liable`

### 📊 État des tests

- **302 tests OK** (2 skipped)
- Nouveaux tests : `test_wallet_split.py` (17 tests), `test_free_tickets.py`
  (7 tests), `test_free_tickets_claim.py` (7 tests), `test_events_video.py`
  (14 tests)

### 🚀 État preprod

- **Dernière migration appliquée :** `dashboard.0016`
- **Dernier commit déployé :** `d6c1864`
- **Tag rollback :** `preprod-avant-vague2-video` (Vague 2)
- **Toutes les features ci-dessus sont en ligne et testées.**

### ⏳ Backlog

| Priorité | Chantier | Effort estimé |
|---|---|---|
| 🔴 Haute | **EventDay + Pass multi-jours** — un événement peut avoir plusieurs jours, un pass peut couvrir 1 jour ou tous les jours. À cadrer (design + modèle + scanner). | ~1 semaine |
| 🟡 Moyenne | **Bug bouton hero partie gauche** — non résolu, à investiguer | ~1 h |
| 🟡 Moyenne | **SendGrid fallback** — dès que les clés sont reçues | ~1/2 j |
| 🟢 Basse | **Doc PayDunya** (`docs/09-providers-paiement.md`) | ~1/2 j |
| 🟢 Basse | **Vague 3.2** — split multi-source d'un reversement (80k events + 20k store) — non demandé mais possible | ~1 j |

### 📌 Décisions actées

- **Wallet historique :** l'ancien solde global a été attribué entièrement
  à Événements (migration `0015`).
- **Codes gratuits :** nominatifs, quota 20 par défaut, dépassement soumis à
  validation admin. L'organisateur distribue lui-même les codes.
- **Email codes gratuits :** pas d'email de distribution automatique, mais
  email de confirmation après réclamation du billet.
- **Reversement :** 1 seule source par reversement (pas de split multi-source
  pour l'instant).

### 🔧 Notes VPS

- Config nginx `prepod.ivoirpass.com` : `client_max_body_size 110M`
  (voir `docs/vps/nginx-prepod.conf.md`). Ne pas remettre à 20M.
- Migrations `.py` : **toujours rebuild l'image Docker** avant `migrate`
  (le container ne voit pas les nouveaux fichiers sinon).

### 💡 Leçons de la session

- **Toujours vérifier `git status` avant de committer** — on a oublié des
  fichiers 2 fois (migration `0006` puis `service.py + templates`).
- **Rebuild Docker obligatoire** après tout ajout de fichier `.py`
  (migrations, vues, tests…). `collectstatic` seul ne suffit pas.
- **Ne pas utiliser `A 2>/dev/null || B`** dans les commandes shell pour
  les push git — ça part en boucle si `A` ne fait rien.
