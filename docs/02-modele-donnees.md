# 02 — Modèle de données

**Modèles Django, relations et migrations.**
Public cible : devs back-end, maintenance.

---

## 1. Vue d'ensemble

La base est organisée autour de **5 domaines** :

| Domaine | App | Rôle |
|---|---|---|
| **Comptes** | `accounts` | Utilisateurs, KYC, adresses |
| **Événements** | `events` | Catalogue culturel (concerts, formations...) |
| **Billetterie** | `tickets` | Commandes, billets, QR |
| **Boutique** | `store` | Produits physiques/numériques, commandes |
| **Finance** | `dashboard` | Wallets, transactions, reversements |
| **Scanner** | `scanner` | Sessions de scan, logs |
| **Paiements** | `payments` | Ligne Payment (traçabilité PayDunya) |
| **Notifications** | `notifications` | Alertes admin |

---

## 2. App `accounts`

### 2.1 `CustomUser`

Utilisateur étendu (email comme identifiant).

| Champ clé | Type | Notes |
|---|---|---|
| `email` | EmailField | **USERNAME_FIELD** |
| `role` | CharField | `organizer`, `scanner`, `admin`, `finance`, `support`, `auditor` |
| `notify_email` | BooleanField | Abonnement aux alertes email admin |
| `managed_by` | FK self | Un organisateur gère ses agents scanner |
| `is_organizer_verified` | BooleanField | **Signal KYC officiel** |
| `kyc_identity_doc` | FileField | CNI (upload) |
| `kyc_proof_of_address` | FileField | Justificatif domicile |
| `kyc_business_doc` | FileField | Document entreprise (optionnel) |
| `kyc_submitted_at` | DateTimeField | Date soumission |
| `kyc_verified_at` | DateTimeField | Date validation |
| `kyc_verified_by` | FK self | Admin validateur |
| `kyc_notes` | TextField | Notes internes |

**Propriétés calculées** (non stockées) :
- `is_organizer` → `role == 'organizer'`
- `is_scanner_agent` → `role == 'scanner'`
- `is_platform_admin` → `role == 'admin'`

**Règle** : `is_organizer_verified` est la **source de vérité** pour le KYC. Ne pas utiliser `kyc_verified_at` directement.

### 2.2 `UserAddress`

Adresses de livraison (boutique physique).

| Champ | Type |
|---|---|
| `user` | FK `CustomUser` |
| `label` | CharField |
| `address` | TextField |
| `city`, `commune`, `country` | CharField |
| `latitude`, `longitude` | DecimalField (nullable) |

---

## 3. App `events`

### 3.1 `Category`

Catégories d'événements.

| Champ | Type |
|---|---|
| `name` | CharField (unique) |
| `slug` | SlugField |
| `icon` | CharField (classe Bootstrap Icons) |
| `color` | CharField (hex) |
| `is_active` | BooleanField |
| `order` | PositiveIntegerField |

### 3.2 `Event`

| Champ | Type | Notes |
|---|---|---|
| `uuid` | UUIDField | Identifiant public |
| `slug` | SlugField | URL |
| `title`, `subtitle` | CharField | |
| `description` | TextField | |
| `short_description` | CharField(150) | **InfoLine** (numéro contact) |
| `category` | FK `Category` | |
| `organizer` | FK `CustomUser` | |
| `scanner_agents` | M2M `CustomUser` | Agents assignés |
| `start_date`, `end_date` | DateTimeField | |
| `doors_open` | TimeField | |
| `event_type` | CharField | `physical`, `online` |
| `venue_name`, `venue_address`, `venue_city`, `venue_country` | — | Lieu |
| `venue_latitude`, `venue_longitude` | DecimalField | Géoloc |
| `online_link` | URLField | Si événement en ligne |
| `cover_image`, `thumbnail` | ImageField | |
| `video_url` | URLField | |
| `min_price` | DecimalField | Prix minimum (calculé) |
| `total_capacity` | PositiveIntegerField | |
| `tickets_sold` | PositiveIntegerField | Compteur (editable=False) |
| `status` | CharField | `draft`, `published`, `cancelled`, `archived` |
| `is_featured` | BooleanField | |
| `commission_rate` | DecimalField | Défaut 8 % |
| `commission_negotiated` | BooleanField | |

**Propriétés** : `is_on_sale`, `is_past`, `is_ongoing`.

### 3.3 `TicketType`

Types de billets par événement (VIP, Standard, Early Bird).

| Champ | Type |
|---|---|
| `event` | FK `Event` |
| `name` | CharField |
| `description` | TextField |
| `price` | DecimalField (min 100 FCFA) |
| `valid_date` | DateField (nullable) — billet valable 1 jour précis |
| `quantity` | PositiveIntegerField — 0 = illimité |
| `quantity_sold` | PositiveIntegerField |
| `max_per_order` | PositiveIntegerField |

---

## 4. App `tickets` — Billetterie

Le tunnel **guest** est le canal actif. Le tunnel "avec compte" existe encore mais n'est plus exposé.

### 4.1 Tunnel "avec compte" (legacy mais conservé)

#### `Order`

| Champ | Type |
|---|---|
| `order_number` | CharField (unique) |
| `uuid` | UUIDField |
| `buyer` | FK `CustomUser` |
| `status` | `pending`, `paid`, `cancelled`, `refunded` |
| `total` | DecimalField |
| `payment_method`, `payment_reference` | CharField |
| `paid_at` | DateTimeField |

#### `OrderItem`

| Champ | Type |
|---|---|
| `order` | FK `Order` |
| `ticket_type` | FK `TicketType` |
| `quantity` | PositiveIntegerField |
| `unit_price`, `subtotal` | DecimalField |

#### `Ticket`

| Champ | Type | Notes |
|---|---|---|
| `uuid` | UUIDField | |
| `ticket_number` | CharField (unique) | |
| `qr_code_data` | CharField(500) | **HMAC-SHA256** signé |
| `qr_code_image` | ImageField | |
| `order_item` | FK `OrderItem` | |
| `status` | `valid`, `used`, `expired`, `void` | |
| `scanned_at` | DateTimeField | |
| `scanned_by` | FK `CustomUser` | |

### 4.2 Tunnel guest (canal actif)

#### `GuestOrder`

| Champ | Type |
|---|---|
| `order_number` | CharField (unique) |
| `first_name`, `last_name`, `email`, `phone` | — |
| `subtotal`, `total` | DecimalField |
| `status` | `pending`, `paid`, `cancelled`, `refunded` |
| `payment_method`, `payment_reference` | CharField |
| `paid_at` | DateTimeField |

#### `GuestOrderItem`

Identique à `OrderItem` mais lié à `GuestOrder`.

#### `GuestTicket`

| Champ | Type | Notes |
|---|---|---|
| `uuid` | UUIDField | |
| `ticket_number` | CharField (unique) | |
| `qr_code_data` | CharField(500) | HMAC-SHA256 |
| `order_item` | FK `GuestOrderItem` | |
| `status` | `valid`, `used`, `void` | |
| `online_access_token` | CharField | Événements en ligne |
| `scanned_at` | DateTimeField | |

**Note** : `GuestTicket` n'a **pas** de `scanned_by` (pas de compte agent lié).

---

## 5. App `store` — Boutique culturelle

### 5.1 Modèles actifs

#### `ProductCategory`

Identique à `events.Category` (name, slug, icon, color, order).

#### `Product`

Produit culturel (livre, album, objet).

| Champ | Type | Notes |
|---|---|---|
| `uuid`, `slug` | — | |
| `name`, `subtitle`, `description` | — | |
| `short_description` | TextField | **InfoLine** (contact vendeur) |
| `category` | FK `ProductCategory` | |
| `product_type` | CharField | `physical`, `digital`, `bundle` |
| `seller` | FK `CustomUser` | |
| `cover_image` | ImageField | Validators : extensions + taille max 5 Mo |
| `preview_file` | FileField | Max 20 Mo |
| `digital_file` | FileField | Validators selon type réel |
| `external_url` | URLField | Lien Spotify/Deezer/Bandcamp (prioritaire sur `digital_file`) |
| `author`, `publisher`, `year`, `language`, `pages`, `duration`, `isbn` | — | Métadonnées |
| `price` | DecimalField | **Min 500 FCFA** |
| `price_physical`, `price_digital` | DecimalField | Pour bundles |
| `stock` | PositiveIntegerField | 0 pour numérique illimité |
| `sold_count` | PositiveIntegerField | |
| `download_limit` | PositiveIntegerField | Défaut 3 |
| `download_expiry_hours` | PositiveIntegerField | Défaut 48 |
| `status` | CharField | `draft`, `published`, `out_stock`, `archived` |
| `commission_rate` | DecimalField | Défaut 8 % |

**Propriétés** : `is_digital`, `is_physical`, `is_available`, `is_available_physical`, `is_available_digital`, `file_extension`, `file_size_mb`.

#### `GuestProductOrder`

| Champ | Type |
|---|---|
| `order_number` | CharField (unique) |
| `first_name`, `last_name`, `email`, `phone` | — |
| `product` | FK `Product` |
| `quantity` | PositiveIntegerField |
| `unit_price`, `subtotal`, `total` | DecimalField |
| `delivery_method` | `download`, `delivery`, `both` |
| Adresse livraison | `delivery_name`, `delivery_phone`, `delivery_address`, `delivery_city`, `delivery_commune`, `delivery_country`, `delivery_instructions` |
| `status` | `pending`, `paid`, `cancelled`, `refunded`, `shipped`, `delivered` |

#### `GuestDownloadLink`

| Champ | Type | Notes |
|---|---|---|
| `token` | UUIDField | URL de téléchargement |
| `order` | FK `GuestProductOrder` | |
| `product` | FK `Product` | |
| `download_count` | PositiveIntegerField | Consommé sur téléchargement fichier |
| `external_click_count` | PositiveIntegerField | **Nouveau (2026-09)** — compteur clics externes (n'impacte PAS la limite) |
| `max_downloads` | PositiveIntegerField | |
| `expires_at` | DateTimeField | |

### 5.2 Modèles legacy 🏛️

> **⚠️ NE PAS SUPPRIMER** — LUS par le back-office financier, les exports admin, le rapport BCEAO et les factures PDF.

#### `ProductOrder` 🏛️

Ancien tunnel "avec compte" boutique (désactivé).
Voir commentaire `LEGACY` en tête de classe dans `apps/store/models.py`.

#### `DownloadLink` 🏛️

Ancien lien de téléchargement pour `ProductOrder`.
Voir commentaire `LEGACY` en tête de classe.

---

## 6. App `dashboard` — Finance & audit

### 6.1 `OrganizerWallet`

Portefeuille électronique de l'organisateur.

| Champ | Type |
|---|---|
| `organizer` | OneToOneField `CustomUser` |
| `balance_available` | DecimalField |
| `balance_pending` | DecimalField |
| `balance_withdrawn` | DecimalField |
| `preferred_payout_method` | CharField (`wave`, `orange_money`, `mtn_momo`, `moov`) |
| `payout_phone`, `payout_name` | CharField |
| **`is_frozen`** | **BooleanField** (nouveau 2026-09) — gel sur annulation |
| **`frozen_reason`** | **TextField** (nouveau 2026-09) |

**Gel** : déclenché par `cancel_event_organizer_liable()` quand un événement avec ventes est annulé. Bloque les demandes de retrait tant qu'un admin n'a pas dégelé manuellement (pas d'UI dédiée).

### 6.2 `WalletTransaction`

| Champ | Type |
|---|---|
| `wallet` | FK `OrganizerWallet` |
| `type` | `credit`, `debit` |
| `amount` | DecimalField |
| `description`, `reference` | CharField |
| Contrainte unique | `(wallet, reference, type=credit)` — idempotence |

### 6.3 `WithdrawalRequest`

| Champ | Type |
|---|---|
| `wallet` | FK |
| `reference` | CharField |
| `amount` | DecimalField |
| `status` | `pending`, `processing`, `completed`, `rejected` |
| `payout_method`, `payout_phone`, `payout_name` | — |

### 6.4 `AuditLog`

Journal d'audit global (payments, scans, exports, annulations...).

| Champ | Type |
|---|---|
| `action` | CharField (choices — nombreux types) |
| `description` | TextField |
| `user` | FK `CustomUser` (nullable) |
| `model_name`, `object_id` | CharField |
| `metadata` | JSONField |
| `ip_address` | GenericIPAddressField |
| `created_at` | DateTimeField |

### 6.5 Autres modèles

- `Dispute` — réclamations clients
- `ReversalOTP` — OTP pour validation des reversements
- `AutomaticPayout` — configuration reversements automatiques

---

## 7. App `scanner`

### 7.1 `ScanSession`

Une session = un agent + un événement + une date.

| Champ | Type |
|---|---|
| `agent` | FK `CustomUser` |
| `event` | FK `Event` |
| `started_at`, `ended_at` | DateTimeField |
| `total_scanned`, `total_valid`, `total_rejected` | PositiveIntegerField |

### 7.2 `ScanLog`

Chaque tentative de scan.

| Champ | Type | Notes |
|---|---|---|
| `session` | FK `ScanSession` | |
| `ticket` | FK `Ticket` (nullable) | Null pour GuestTicket |
| `qr_data_received` | CharField(500) | |
| `result` | CharField | `valid`, `already_used`, `invalid_qr`, `wrong_event`, `ticket_void`, `not_found` |
| `scanned_at` | DateTimeField | |
| **`client_uuid`** | **UUIDField** (nullable, indexé) | **Nouveau (2026-09)** — idempotence sync offline |

**Idempotence** : si un `client_uuid` est déjà traité pour la session, `sync_offline_scans` renvoie le résultat original sans créer de nouvelle ligne.

---

## 8. App `payments`

### 8.1 `Payment`

Traçabilité des paiements PayDunya.

| Champ | Type | Notes |
|---|---|---|
| `order` | FK `Order` (nullable) | Tunnel avec compte |
| `guest_order` | FK `GuestOrder` (nullable) | Tunnel guest billetterie |
| `guest_product_order` | FK `GuestProductOrder` (nullable) | Boutique |
| `store_order` | FK `ProductOrder` (nullable) | 🏛️ Legacy |
| `amount`, `currency` | DecimalField, CharField | |
| `provider` | CharField | `paydunya` |
| `paydunya_token`, `paydunya_invoice_token` | CharField | |
| `status` | CharField | `pending`, `completed`, `cancelled`, `failed` |
| `raw_response` | JSONField | |
| `created_at`, `completed_at` | DateTimeField | |

**Note** : une seule ligne `Payment` par commande. Créée à l'initiation PayDunya, mise à jour au webhook.

---

## 9. App `notifications`

### 9.1 `AdminNotification`

Alertes destinées aux admins (stock conflicts, anomalies).

| Champ | Type |
|---|---|
| `user` | FK `CustomUser` |
| `subject`, `message` | — |
| `is_read` | BooleanField |
| `created_at` | DateTimeField |

---

## 10. Migrations — Historique clé

### 10.1 Comptes
- `000_initial` → création `CustomUser`
- `0002` → champs KYC
- `0006` → rôles `finance`, `support`, `auditor`
- `0007` → `managed_by` (agents scanner)

### 10.2 Events
- `0009` → suppression `is_free` (retrait logique événement gratuit)
- `0009` → `MinValueValidator(100)` sur `TicketType.price`

### 10.3 Store
- `0009` → `GuestProductOrder.delivery_method` (ajout `both`)
- `0010` → standardisation `download_limit` (3/48h)
- `0011` → **validateurs upload** + `MinValueValidator(500)` + `short_description` → InfoLine
- `0012` → **`external_url`** + `external_click_count`
- `0013` → **fix extensions sans point** (Django strip le `.`)

### 10.4 Dashboard
- `0009` → contrainte unique wallet-credit
- `0010` → actions réconciliation
- `0013` → **`OrganizerWallet.is_frozen` + `frozen_reason`**

### 10.5 Scanner
- `0002` → **`ScanLog.client_uuid`** (idempotence offline)

### 10.6 Payments
- `0003` → `Payment.guest_order`
- `0004` → FK boutique (`guest_product_order`, `store_order`)

### 10.7 Tickets
- `0004` → protection annulation paiement
- `0005` → `GuestTicket.online_access_token`

---

## 11. Points d'attention maintenance

### 🏛️ Legacy à conserver
- `ProductOrder`, `DownloadLink` — lus par le back-office financier, exports admin, rapport BCEAO, factures PDF. **Ne pas supprimer** sans chantier dédié.

### ⚠️ Contraintes à respecter
- **`Event.tickets_sold`** : `editable=False` → update uniquement via `QuerySet.update()` avec `F()`
- **`Product.sold_count`** : idem
- **Wallet** : contrainte unique sur `(wallet, reference, type=credit)` — idempotence crédits
- **`is_organizer_verified`** : utiliser cette propriété, pas `kyc_verified_at`
- **`client_uuid`** : nullable — toujours vérifier `if client_uuid` avant les recherches d'idempotence

### 🚨 Pièges connus
- `FileExtensionValidator` Django attend des extensions **sans point** (`['png']`, pas `['.png']`)
- `GuestTicket.online_access_token` peut être vide pour les événements physiques
- `Payment.order` / `guest_order` / `guest_product_order` : seul **un** est renseigné selon le type de commande

---

## 📅 Dernière mise à jour

2026-09-27 — Documentation initiale.