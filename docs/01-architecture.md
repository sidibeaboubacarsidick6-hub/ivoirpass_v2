markdown
# 01 — Architecture technique

**Vue d'ensemble de l'architecture IvoirPass V2.**
Public cible : nouveaux devs, devops, maintenance.

---

## 1. Vue d'ensemble
┌──────────────┐ ┌──────────────┐ ┌────────────────┐
│ Navigateur │─────────│ Nginx │─────────│ Gunicorn │
│ (acheteur, │ HTTPS │ (reverse │ HTTP │ (Django WSGI) │
│ organisateur│ │ proxy) │ │ │
│ agent scan) │ └──────────────┘ └────────┬───────┘
└──────────────┘ │
│
┌─────────────────────────────────┼─────────────┐
│ │ │
▼ ▼ ▼
┌───────────────┐ ┌──────────────┐ ┌───────────┐
│ PostgreSQL │ │ Redis │ │ Celery │
│ (données) │ │ (cache, │ │ worker │
│ │ │ broker, │ │ + beat │
│ │ │ sessions) │ │ │
└───────────────┘ └──────────────┘ └───────────┘
│
▼
┌──────────────┐
│ PayDunya │
│ (webhook) │
└──────────────┘

text

**Scanner PWA offline** : l'app `/scanner/app/` fonctionne en mode avion grâce à :
- Service Worker (cache app shell + libs)
- IndexedDB (cache billets + queue de scans)
- Sync différée vers `/api/scanner/sync/` quand la connexion revient

---

## 2. Stack technique

| Composant | Technologie | Version |
|---|---|---|
| Backend | Django | 4.2 |
| API REST | Django REST Framework | 3.15 |
| Auth API | djangorestframework-simplejwt | 5.5 |
| Base de données | PostgreSQL | 15 |
| Cache / broker | Redis | 7 |
| Tâches asynchrones | Celery + Celery Beat | 5.4 |
| Frontend | Bootstrap 5 + Alpine.js | — |
| Auth web | django-allauth | 65.14 |
| Rate limiting | django-ratelimit | 4.1 |
| Génération PDF | ReportLab | 4.2 |
| QR Code (génération) | qrcode | 7.4 |
| QR Code (lecture) | html5-qrcode | 2.3.8 (servi en local) |
| Paiement | PayDunya (Wave, Orange Money, MTN) | API v2 |
| Monitoring | Sentry | 2.19 |
| Déploiement | Docker Compose + OVH Ubuntu + Nginx + Gunicorn | — |
| CI | GitHub Actions (tests à chaque push) | — |

---

## 3. Structure du projet
ivoirpass_v2/
├── config/ # Configuration Django
│ ├── settings/
│ │ ├── base.py # Settings communs
│ │ ├── development.py # Dev local (DEBUG=True)
│ │ ├── testlocal.py # Tests (SQLite mémoire, Celery eager)
│ │ └── production.py # Preprod + prod (DEBUG=False)
│ ├── celery.py # App Celery
│ └── urls.py # URLs racine
│
├── apps/
│ ├── accounts/ # Utilisateurs + KYC + API JWT
│ ├── core/ # Pages statiques (FAQ, CGU, contact)
│ ├── events/ # Événements + types de billets
│ ├── tickets/ # Billetterie (Order, GuestOrder, Ticket, GuestTicket)
│ ├── payments/ # Intégration PayDunya + réconciliation
│ ├── dashboard/ # Back-office organisateur + admin + wallet + BCEAO
│ ├── scanner/ # Scanner QR (web + PWA + API)
│ ├── store/ # Boutique culturelle (produits, commandes)
│ └── notifications/ # Email + SMS + templates
│
├── templates/ # Templates Django
│ ├── scanner_app/ # PWA scanner (autonome, avec SW)
│ ├── notifications/email/ # Emails transactionnels
│ └── ...
│
├── static/
│ ├── css/, js/, images/ # Assets site principal
│ └── scanner-app/ # Assets PWA (sw.js, manifest, html5-qrcode.min.js)
│
├── media/ # Fichiers uploadés (avatars, KYC, covers, digital)
├── tests/ # Tests unitaires
├── docs/ # Cette documentation
├── run_dev.sh # Script de lancement local
├── Dockerfile # Image Docker
└── docker-compose.preprod.yml # Compose preprod (5 services)

text

---

## 4. Applications Django

| App | Rôle | Modèles principaux |
|---|---|---|
| `accounts` | Comptes utilisateurs, KYC, rôles | `CustomUser`, `UserAddress` |
| `core` | Pages publiques statiques | — |
| `events` | Catalogue événements | `Event`, `Category`, `TicketType` |
| `tickets` | Billetterie (achat, QR, billets) | `Order`, `OrderItem`, `Ticket`, `GuestOrder`, `GuestOrderItem`, `GuestTicket` |
| `payments` | Intégration + suivi paiements | `Payment` |
| `dashboard` | Back-office organisateur + admin | `OrganizerWallet`, `WalletTransaction`, `WithdrawalRequest`, `AuditLog`, `Dispute` |
| `scanner` | Scan QR | `ScanSession`, `ScanLog` |
| `store` | Boutique culturelle | `Product`, `ProductCategory`, `GuestProductOrder`, `GuestDownloadLink` |
| `notifications` | Emails + SMS | `AdminNotification` |

---

## 5. Flux applicatifs

### 5.1 Billetterie (tunnel guest — canal actif)
Visiteur → /evenements/ → choisit événement → /billets/acheter/<slug>/
→ GuestOrder créé (PENDING)
→ PayDunya checkout (redirection)
→ Webhook PayDunya → vérification serveur-à-serveur
→ GuestOrder PAID + GuestTicket générés (QR signé HMAC)
→ Email de confirmation avec PDF en pièce jointe
→ Wallet organisateur crédité (net après commission)

text

Le tunnel "avec compte" (`Order` / `ProductOrder`) existe encore mais n'est plus exposé.

### 5.2 Boutique culturelle (tunnel guest)
Visiteur → /boutique/ → produit → /boutique/acheter/<slug>/
→ GuestProductOrder créé (PENDING)
→ PayDunya checkout
→ Webhook → vérification → PAID
→ GuestDownloadLink généré (fichier interne ou external_url)
→ Email avec liens
→ Wallet vendeur crédité

text

Pour un produit `external_url` (Spotify, Deezer, Bandcamp) :
- La route `/boutique/guest/telecharger/<token>/` incrémente un compteur puis redirige vers l'URL externe.

### 5.3 Scanner QR (online + offline)

**Online** : navigation classique `/scanner/app/` → login → saisie ID événement → scan
**Offline** : pré-chargement des billets via `POST /api/scanner/prepare/<event_id>/` → cache IndexedDB → scan local → queue → sync auto
Agent → /scanner/app/
→ Préparer événement → tickets cachés en IndexedDB
→ (Mode avion possible)
→ Scan → validation locale (cache-first)
├── Billet en cache → décision locale + queue
└── Billet hors cache → fallback API (si online)
→ Retour en ligne → sync auto (batches de 100)
→ ScanLog créé côté serveur avec client_uuid (idempotence)

text

### 5.4 Dashboard organisateur
Organisateur → /dashboard/
├── Ventes, revenus, commissions
├── Wallet (solde, historique, demandes de retrait)
├── Liste événements + boutons Annuler/Supprimer
├── Livraisons physiques à expédier
├── Rapports BCEAO (exports CSV/Excel/PDF)
└── Journal d'audit

text

### 5.5 Admin plateforme

Réservé au staff :
- `/admin/` — Django admin natif
- `/admin/bceao-report/` — rapport financier
- `/admin/export/{csv,excel}/` — exports globaux
- `/dashboard/transactions/` — back-office financier

---

## 6. Environnements

| Env | Config | DB | Celery | Email | Usage |
|---|---|---|---|---|---|
| **dev** | `development.py` | PostgreSQL ou SQLite | Redis local | Console | Développement local |
| **testlocal** | `testlocal.py` | SQLite en mémoire | Eager (synchrone) | Locmem | CI + tests unitaires |
| **preprod** | `production.py` | PostgreSQL Docker | Worker + Beat Docker | SMTP | Validation avant prod |
| **prod** | `production.py` | PostgreSQL VPS | Worker + Beat | SMTP | Production |

**Variables critiques** (`.env`) :
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`
- `DB_*`, `REDIS_URL`, `CELERY_*`
- `PAYDUNYA_*` (mode test/live)
- `EMAIL_*`, `ADMIN_EMAIL`

---

## 7. Communication entre composants

### 7.1 Celery + Beat

| Tâche | Déclencheur | Rôle |
|---|---|---|
| Emails transactionnels | Sur action (signal ou vue) | Billets, KYC, annulations |
| Réconciliation paiements | Beat (toutes les 20 min) | Rattrapage des PENDING |
| Alertes anomalies | Beat | Notif admins (Sentry + email) |
| Reversements automatiques | Beat (hebdo) | Prélèvement wallet |

**Règle de déploiement** : toujours `docker compose build` **sans argument** + `up -d --force-recreate`. Ne jamais rebuild uniquement `web` — Celery/Beat garderaient l'ancienne image.

### 7.2 PayDunya

- Redirection acheteur → PayDunya
- **Webhook** reçu sur `/paiements/webhook/` ou `/boutique/guest/webhook/`
- **Vérification serveur-à-serveur** systématique (pas de confiance aveugle au webhook)
- Gestion idempotente (retry webhook n'entraîne pas de double paiement)

### 7.3 Scanner offline (PWA)

- **Service Worker** (`/scanner/app/sw.js`) : cache app shell + statiques
- **IndexedDB** (`ivoirpass_scanner`) : 2 stores → `tickets`, `scan_queue`
- **Sync auto** : event `online` + après chaque scan + au démarrage
- **Idempotence** : `ScanLog.client_uuid` empêche le doublon de sync

**⚠️ Points d'attention déploiement** :
- `collectstatic` obligatoire à chaque ajout/modif dans `static/`
- **Bump `CACHE_NAME`** dans `sw.js` (v1 → v2...) si `index.html` change
  → sinon les mobiles gardent l'ancienne version pendant des jours

---

## 8. Décisions architecturales verrouillées

| # | Décision | Date | Contexte |
|---|---|---|---|
| 1 | **Guest-first** : pas de compte requis pour acheter | 2026 | Réduit la friction d'achat, aligné mobile-first |
| 2 | **Tunnel "avec compte" désactivé** (routes redirigées) | 2026-09 | Simplifie la maintenance, un seul canal à sécuriser |
| 3 | **Scanner PWA offline-first** | 2026-09-27 | Zones blanches terrain (stade, salle) |
| 4 | **Billetterie et boutique séparées** (2 apps, 2 tunnels) | 2026-06 | Modèles et flux distincts, mais code cohérent |
| 5 | **Commission prélevée sur l'organisateur** | 2026 | Jamais sur l'acheteur — prix affiché = prix payé |
| 6 | **KYC via `is_organizer_verified`** (BooleanField) | 2026-09-27 | Source de vérité unique, plus fiable que `kyc_verified_at` |
| 7 | **Signature HMAC sur les QR codes** | 2026 | Anti-falsification |
| 8 | **Verrou anti-double-scan** (`select_for_update`) | 2026 | Deux agents simultanés ne peuvent pas valider le même billet |
| 9 | 🏛️ **`ProductOrder` / `DownloadLink` conservés** | 2026-09-27 | LUS par back-office financier, BCEAO, factures PDF |
| 10 | ⏭️ **Watermark MP3 non implémenté** | 2026-09-27 | Complexité ré-encodage ID3 |

Légende :
- ✅ actif et verrouillé
- 🏛️ legacy conservé (voir commentaires `LEGACY` dans `apps/store/models.py`)
- ⏭️ reporté à un chantier dédié

---

## 9. Limites connues

- **App mobile native** (iOS/Android) : non développée. Le scanner est une PWA installable depuis le navigateur.
- **Multi-pays** : non supporté. Focus Côte d'Ivoire uniquement.
- **Multi-devises** : XOF uniquement.
- **Plan de salle interactif** : non implémenté.

---

## 📅 Dernière mise à jour

2026-09-27 — Documentation initiale.