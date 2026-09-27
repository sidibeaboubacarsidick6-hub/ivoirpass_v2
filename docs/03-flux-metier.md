# 03 — Flux métier

**Parcours utilisateurs et flux fonctionnels détaillés.**
Public cible : devs, product, support.

---

## 1. Vue d'ensemble

| Flux | Acteurs | Canal |
|---|---|---|
| Billetterie | Acheteur guest | Public |
| Boutique culturelle | Acheteur guest | Public |
| KYC organisateur | Organisateur | Dashboard |
| Paiement PayDunya | Acheteur → PayDunya → IvoirPass | Transversal |
| Annulation événement | Organisateur ou Admin | Dashboard / Admin |
| Scanner QR (online) | Agent | `/scanner/app/` |
| Scanner QR (offline) | Agent | PWA installée |
| Livraison physique | Organisateur | Dashboard |
| Reversement wallet | Organisateur | Dashboard |

---

## 2. Flux billetterie (guest)

**Canal actif** — aucun compte requis.

### 2.1 Parcours acheteur
Découverte
/evenements/ → filtre / recherche
→ /evenements/<slug>/ (détail)

Choix du billet
Sélection type + quantité
→ clic "Acheter"

Formulaire invité
/billets/acheter/<slug>/

Prénom, nom, email, téléphone

Adresse si livraison physique

Redirect vers /billets/guest/payer/<order_number>/

Paiement
Initiation PayDunya (POST /checkout-invoice/create)

Création Payment (status=PENDING)

AuditLog PAYMENT_INITIATED

Redirect vers PayDunya

Retour

Retour navigateur : /billets/guest/retour/<order_number>/

Webhook : /billets/guest/webhook/

Confirmation
Vérification serveur-à-serveur PayDunya
GuestOrder → PAID
GuestTicket(s) générés (QR HMAC)
Email avec PDF joint
Wallet organisateur crédité (net après commission)
→ /billets/guest/confirmation/<order_number>/

text

### 2.2 États de `GuestOrder`
PENDING ──(webhook OK)──► PAID ──(annulation événement)──► CANCELLED
│
└──(cancel_url)──► CANCELLED

text

**Règles** :
- Une commande `CANCELLED` est **terminale** : un webhook tardif ne peut pas la repasser à `PAID`.
- Idempotence : `mark_as_paid()` est verrouillée par `select_for_update` + vérification `status == PENDING`.

### 2.3 Génération des billets

À la confirmation :
- 1 `GuestTicket` par unité achetée
- `qr_code_data` = `uuid:ticket_number:...:signature_hmac` (signé serveur)
- `online_access_token` si l'événement est en ligne
- Envoi email avec PDF (filigrane si boutique)

---

## 3. Flux boutique culturelle (guest)

### 3.1 Parcours acheteur
Découverte
/boutique/ → filtre par catégorie, type

Détail
/boutique/<slug>/

Cover, description, prix

Bouton "Acheter"

Formulaire invité
/boutique/acheter/<slug>/

Prénom, nom, email, téléphone

Si bundle : choix format (numérique / physique / both)

Si physique : adresse complète

Redirect vers /boutique/guest/payer/<order_number>/

Paiement
Idem billetterie (PayDunya)
GuestProductOrder créée PENDING

Confirmation
Verification serveur-à-serveur
GuestProductOrder → PAID
GuestDownloadLink(s) généré(s)
Email avec liens de téléchargement
Wallet vendeur crédité

text

### 3.2 Cas spécifique : produit avec `external_url`

Pour un produit avec `Product.external_url` (Spotify, Deezer, Bandcamp) :
- Le lien généré dans l'email pointe vers `/boutique/guest/telecharger/<token>/`
- Cette route :
  1. Incrémente `GuestDownloadLink.external_click_count` (atomique via `F()`)
  2. Redirige vers `product.external_url`
  3. **Ne consomme PAS** `download_count` (limite de downloads)

**Priorité** : si `external_url` ET `digital_file` sont renseignés, `external_url` est servi en priorité (pour compter les clics).

### 3.3 Cas spécifique : bundle avec `stock=0`

Un bundle (`product_type='bundle'`) avec `stock=0` :
- **Reste visible et achetable** en version numérique
- **Bloqué** en version physique avec message : *"Version physique épuisée. Choisissez la version numérique pour continuer."*

Détection via `Product.is_available_physical` (stock > 0).

### 3.4 États de `GuestProductOrder`
PENDING ──(webhook)──► PAID ──(annulation vendeur)──► CANCELLED
│ │
│ └──(livraison)──► SHIPPED ──► DELIVERED
│
└──(cancel_url)──► CANCELLED

text

---

## 4. Flux KYC organisateur

### 4.1 Parcours de validation
Inscription
→ compte avec role='organizer' (par défaut)
→ is_organizer_verified = False

Profil
/accounts/profil/ → onglet Organisation
→ "Complétez mon profil organisateur"

Upload KYC
/accounts/profil/modifier/ (section Vérifications KYC)

kyc_identity_doc (CNI)

kyc_proof_of_address (justificatif domicile)

kyc_business_doc (optionnel)
→ kyc_submitted_at = now()

Validation admin
/admin/accounts/customuser/
→ action "Valider KYC"
→ is_organizer_verified = True
→ kyc_verified_at = now()
→ kyc_verified_by = <admin>

Publication autorisée
Organisateur peut publier événements et produits

text

### 4.2 Règles KYC

**Publication d'événement** :
- Statut `DRAFT` : pas de KYC requis
- Statut `PUBLISHED` : `is_organizer_verified` obligatoire
- Message persistant si non vérifié (`extra_tags='danger kyc-persistent'`)

**Publication de produit boutique** :
- Idem : KYC obligatoire pour `PUBLISHED`
- Décision verrouillée : pas de distinction gratuit/payant

---

## 5. Flux paiement PayDunya

### 5.1 Initiation
Client clique "Payer"
POST vers la vue payment_initiate

Création ligne Payment (status=PENDING)

amount, currency=XOF

provider='paydunya'

paydunya_token (retourné par PayDunya)

Envoi payload à PayDunya
POST /checkout-invoice/create
{ store, invoice, actions{return_url,cancel_url,callback_url}, custom_data }

Réponse PayDunya

response_code '00' → redirect vers response_text (URL PayDunya)

sinon → erreur + AuditLog PAYMENT_FAILED

text

### 5.2 Webhook (2 points d'entrée)

| URL | Contexte |
|---|---|
| `/paiements/webhook/` | Billetterie avec compte (legacy) |
| `/billets/guest/webhook/` | Billetterie guest |
| `/boutique/guest/webhook/` | Boutique guest |

**Traitement** :
1. Vérification signature PayDunya (`verify_webhook_signature`)
2. Extraction `order_number` depuis `custom_data`
3. **Vérification serveur-à-serveur** via `verify_payment(token)`
4. Si confirmé :
   - `mark_as_paid()` (verrouillé, idempotent)
   - Génération billets / liens
   - Envoi email
   - AuditLog PAYMENT_SUCCESS

### 5.3 Réconciliation

**Celery Beat** exécute `reconcile_pending_payments` toutes les 20 min :
- Cherche les `Payment` en `PENDING` depuis > 48h
- Appelle PayDunya pour vérifier l'état réel
- Si payé → confirme la commande
- Si anomalie → notifie les admins

### 5.4 Règle d'or

**Jamais de confiance aveugle au webhook** : on vérifie toujours serveur-à-serveur via `verify_payment`.

---

## 6. Flux annulation événement (nouveau 2026-09)

### 6.1 Déclenchement

**Organisateur** (depuis `/evenements/mes-evenements/`) :
- Événement avec ventes → bouton orange "🚫 Annuler l'événement"
- Événement sans ventes → bouton rouge "🗑️ Supprimer"

**Admin** (depuis `/admin/events/event/`) :
- Action "🚫 Annuler les événements sélectionnés"

### 6.2 Traitement (`cancel_event_organizer_liable`)
event.status = CANCELLED

Tous les GuestTicket VALID → VOID
→ scanner refusera (statut void)

Tous les Ticket VALID → VOID (legacy)

Tous les GuestOrder PAID → CANCELLED (jamais REFUNDED)

Tous les Order PAID → CANCELLED

Si >= 1 commande PAID :
OrganizerWallet.is_frozen = True
OrganizerWallet.frozen_reason = "..."
→ aucune demande de retrait acceptée

Emails aux acheteurs (event_cancelled_buyer)

Sans numéro organisateur

Sans promesse de remboursement auto

Alerte à tous les admins (event_cancelled_admin_alert)

Nom organisateur, nb commandes, wallet gelé ?

text

### 6.3 Règles verrouillées

- **IvoirPass n'est PAS responsable du remboursement** — c'est l'organisateur
- **Aucun débit wallet automatique** — le wallet est juste **gelé**
- **Dégel manuel** par un admin (pas d'UI dédiée — via Django admin)
- Gèle même si wallet déjà négatif

### 6.4 Réactivation des tickets

**Non supporté** : une fois `VOID`, un ticket ne peut pas être remis à `VALID`. Il faudra refaire un achat.

---

## 7. Flux scanner QR

### 7.1 Scanner online (web)

**Interface** : `/scanner/` (classique, session Django)

**Ou** : `/scanner/app/` (PWA) → login → `/api/scanner/scan/`
Agent scanne → POST /api/scanner/scan/ (ou appel direct via session)
{ qr_data, event_id }

Traitement serveur (_process_scan) :

Parse qr_data → uuid + ticket_number

Récupération Ticket ou GuestTicket (select_for_update)

Vérifications dans l'ordre :

verify_qr() → signature HMAC valide ?

ticket.event == event_id ?

ticket.status == 'void' ?

ticket.status == 'used' ?

Sinon → VALID

Si valide : mark_as_used() (GuestTicket sans scanned_by)

Création ScanLog

AuditLog TICKET_SCANNED

Incrément compteurs session

text

**Verrou anti-double-scan** : `select_for_update` empêche deux agents simultanés de valider le même billet.

### 7.2 Scanner offline (PWA)

**Préparation** :
Agent → /scanner/app/ → login
→ Saisie ID événement → "📥 Préparer hors ligne"
→ POST /api/scanner/prepare/<event_id>/
→ Liste billets (VALID + USED + VOID) + qr_data
→ Stockage IndexedDB (store 'tickets')

text

**Scan (offline)** :
Agent scanne un QR

Parse qr_data → ticket_number

Lookup dans IndexedDB (par ticket_number)
├── Trouvé → décision locale :
│ - status=='void' → TICKET_VOID
│ - status=='used' → ALREADY_USED
│ - status=='valid' → VALID
│ + update statut local à 'used'
│ + ajout à scan_queue (avec client_uuid)
└── Non trouvé :
├── En ligne → fallback POST /api/scanner/scan/
└── Hors ligne → refus "non reconnu"

text

**Sync auto** :
Déclencheurs :

Event 'online' (retour connexion)

Après chaque scan online (différé 800ms)

Au démarrage du scan

Traitement :

Lire scan_queue (non synced)

Découper en batches de 100

POST /api/scanner/sync/ par batch

Retirer les scans traités de la queue

Mettre à jour badge "N en attente"

text

**Idempotence** : si un `client_uuid` a déjà été traité côté serveur (même après un retry réseau), `sync_offline_scans` renvoie le résultat original sans créer de nouveau `ScanLog`.

### 7.3 Restriction agents

Un **agent scanner** ne peut scanner que les événements auxquels il a été **explicitement assigné** (`Event.scanner_agents`). Vérifié via `_authorize_agent_for_event`.

Un **organisateur** ne peut scanner que ses propres événements.

Un **admin plateforme** peut scanner n'importe quel événement.

---

## 8. Flux livraison physique (boutique)

Pour `GuestProductOrder.delivery_method in ('delivery', 'both')` :
À la confirmation du paiement :

Product.stock -= quantity

Product.sold_count += quantity

Notification vendeur (notify_seller_new_order)

Vendeur → /dashboard/commandes-physiques/
Liste des commandes à expédier

Vendeur marque "Expédiée"
→ status = SHIPPED
→ shipped_at = now()
→ tracking_number (optionnel)

Vendeur marque "Livrée" (ou auto)
→ status = DELIVERED

text

**Frais de livraison** : à la charge du client (annoncé dans l'UI).

---

## 9. Flux reversement wallet

### 9.1 Crédit automatique

Après chaque vente confirmée :
WalletTransaction(credit, amount=net)

text
où `net = subtotal × (1 - commission_rate/100)`.

**Idempotence** : contrainte unique sur `(wallet, reference, type=credit)` — empêche un double crédit si `mark_as_paid` est appelé deux fois.

### 9.2 Demande de retrait
Organisateur → /dashboard/wallet/reverser/

Saisit montant (min 5000 FCFA), méthode (Wave/OM/MTN/Moov), numéro

Création WithdrawalRequest (status=PENDING)

Notification email organisateur

Admin → /dashboard/transactions/

Voit la demande

Valide via OTP

Status → PROCESSING → COMPLETED

Email confirmation organisateur

text

### 9.3 Blocage par wallet gelé

Si `OrganizerWallet.is_frozen == True` :
- `/dashboard/wallet/reverser/` redirige immédiatement
- Message : *"Votre wallet est actuellement gelé..."*
- **Aucune `WithdrawalRequest` créée**

**Dégel** : manuel via Django admin (`OrganizerWallet.is_frozen = False`).

---

## 10. Points d'attention

### 10.1 Idempotence partout

| Flux | Protection |
|---|---|
| Paiement | `mark_as_paid()` verrouillé + statut PENDING |
| Crédit wallet | Contrainte unique `(wallet, reference, type)` |
| Scan offline | `ScanLog.client_uuid` |
| Annulation événement | Service verrouillé par `transaction.atomic` |

### 10.2 États terminaux

Ces états ne doivent **jamais** être modifiés par un flux automatique :
- `GuestOrder.CANCELLED`
- `GuestProductOrder.CANCELLED`
- `GuestTicket.VOID`
- `Ticket.VOID`
- `Payment.CANCELLED`

### 10.3 Canal actif unique

**Billetterie** : guest uniquement. Le tunnel "avec compte" existe encore dans le code mais est désactivé (routes redirigées).

**Boutique** : guest uniquement.

Ne pas créer de nouveaux flux sur les tunnels "avec compte".

### 10.4 Celery : redéploiement

Toute modif de `apps/*/tasks.py` ou `apps/notifications/*` nécessite un rebuild **de tous les services** :
```bash
docker compose build              # ← sans argument
docker compose up -d --force-recreate
Sinon Celery/Beat gardent l'ancienne image.