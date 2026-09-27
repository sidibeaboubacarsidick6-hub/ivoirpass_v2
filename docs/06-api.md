# 06 — API & Endpoints

**Endpoints internes, API JSON, webhooks.**
Public cible : devs, intégrateurs.

---

## 1. Vue d'ensemble

IvoirPass expose 3 catégories d'endpoints :

| Catégorie | Préfixe | Auth | Format |
|---|---|---|---|
| **API JSON** | `/api/...` | JWT ou session | JSON |
| **Webhooks PayDunya** | `/paiements/webhook/`, `/billets/guest/webhook/`, `/boutique/guest/webhook/` | Signature PayDunya | JSON |
| **Vues Django internes** | `/...` | Session cookie | HTML ou redirect |

Les webhooks et l'API scanner PWA utilisent la **session Django** (pas de JWT).

---

## 2. API d'authentification (`/api/accounts/`)

### 2.1 JWT

| Méthode | URL | Rôle |
|---|---|---|
| POST | `/api/accounts/token/` | Obtenir access + refresh token |
| POST | `/api/accounts/token/refresh/` | Rafraîchir l'access token |
| POST | `/api/accounts/token/verify/` | Vérifier un token |

**Payload** (token) :
```json
{ "email": "user@test.com", "password": "..." }
Réponse :

json
{ "access": "...", "refresh": "..." }
2.2 Compte
Méthode	URL	Rôle
POST	/api/accounts/register/	Inscription
GET/PUT	/api/accounts/profile/	Profil utilisateur
POST	/api/accounts/change-password/	Changer mot de passe
GET/POST	/api/accounts/addresses/	Liste / création adresses
GET/PUT/DELETE	/api/accounts/addresses/<pk>/	Détail adresse
Auth : JWT (Bearer).

3. API Scanner (/api/scanner/)
Auth : session Django (cookie).

3.1 Scan online
text
POST /api/scanner/scan/
Payload :

json
{ "qr_data": "<uuid>:<number>:...:...", "event_id": 14 }
Réponse :

json
{
  "result": "valid",
  "message": "Accès autorisé ✅",
  "color": "green",
  "ticket_info": {
    "ticket_number": "IP-2026-ABC123",
    "ticket_type": "Standard",
    "buyer_name": "Jean Dupont",
    "event_title": "Concert"
  }
}
Valeurs result : valid, already_used, invalid_qr, wrong_event, ticket_void, not_found.

Status HTTP : 200 (résultat), 400 (payload invalide), 401 (non auth), 403 (agent non autorisé).

3.2 Vérification événement
text
POST /api/scanner/check-event/
Payload : { "event_id": 14 }
Réponse : { "exists": true }

3.3 Préparation offline
text
POST /api/scanner/prepare/<event_id>/
Rôle : renvoie tous les billets de l'événement pour cache IndexedDB côté client.

Réponse :

json
{
  "event_id": 14,
  "event_title": "Concert",
  "generated_at": "2026-09-27T10:30:00Z",
  "tickets": [
    {
      "kind": "guest",
      "uuid": "...",
      "ticket_number": "IP-2026-ABC123",
      "ticket_type": "Standard",
      "buyer_name": "Jean Dupont",
      "qr_data": "...",
      "status": "valid"
    }
  ]
}
Statuts inclus : valid, used, void, expired.

Status HTTP : 200, 401 (non auth), 403 (agent non autorisé), 404 (événement inexistant).

3.4 Synchronisation offline
text
POST /api/scanner/sync/
Payload :

json
{
  "event_id": 14,
  "scans": [
    { "client_uuid": "abc-123", "qr_data": "..." },
    { "client_uuid": "def-456", "qr_data": "..." }
  ]
}
Limite : 500 scans max par batch (au-delà → 400 batch_too_large).

Réponse :

json
{
  "results": [
    { "client_uuid": "abc-123", "result": "valid", "message": "...", "color": "green" },
    { "client_uuid": "def-456", "result": "already_used", "message": "...", "color": "red", "idempotent": true }
  ],
  "session_totals": {
    "total_scanned": 42,
    "total_valid": 40,
    "total_rejected": 2
  }
}
Idempotence : si un client_uuid a déjà été traité → idempotent: true + résultat original.

Status HTTP : 200, 400 (payload invalide), 401, 403, 404.

4. API Scanner mobile (JWT) — legacy
🏛️ Endpoints sous /api/scanner/ avec JWT — utilisés par une éventuelle app mobile native. Non exposés actuellement.

Méthode	URL	Rôle
GET	/api/scanner/my-events/	Événements scannables par l'agent connecté
5. Webhooks PayDunya
5.1 Billetterie guest
text
POST /billets/guest/webhook/
Auth : signature PayDunya (verify_webhook_signature).

Traitement :

Parse custom_data.guest_order_number + invoice.status

Vérification serveur-à-serveur via PayDunyaService.verify_payment(token)

Si completed → mark_as_paid() + email + crédit wallet

Retourne 200 OK (toujours, sauf 403 si signature invalide)

5.2 Boutique guest
text
POST /boutique/guest/webhook/
Idem billetterie guest, avec custom_data.guest_store_order_number.

5.3 Billetterie "avec compte" (legacy)
text
POST /paiements/webhook/
Traitement identique.

Rate limiting : 30/min par IP sur les 3 webhooks.

Règle d'or : jamais de confiance aveugle au webhook — toujours vérification serveur-à-serveur.

6. Vues Django internes (non-API)
Ces URLs répondent en HTML ou en redirect. Pas d'API JSON.

6.1 Billetterie guest
URL	Rôle
/billets/acheter/<slug>/	Formulaire invité
/billets/guest/payer/<order_number>/	Initiation PayDunya
/billets/guest/retour/<order_number>/	Retour après paiement
/billets/guest/annulation/<order_number>/	Annulation
/billets/guest/confirmation/<order_number>/	Page de confirmation
/billets/guest/billet/<ticket_number>/pdf/	Téléchargement PDF
/billets/live/<token>/	Accès événement en ligne (redirige vers Zoom)
6.2 Boutique guest
URL	Rôle
/boutique/	Catalogue
/boutique/<slug>/	Détail produit
/boutique/acheter/<slug>/	Formulaire invité
/boutique/guest/payer/<order_number>/	Initiation PayDunya
/boutique/guest/retour/<order_number>/	Retour
/boutique/guest/annulation/<order_number>/	Annulation
/boutique/guest/confirmation/<order_number>/	Confirmation
/boutique/guest/telecharger/<token>/	Téléchargement sécurisé (ou redirect external_url)
/boutique/mes-produits/	Gestion produits (vendeur)
/boutique/mes-produits/creer/	Création produit
6.3 Événements (organisateur)
URL	Rôle
/evenements/	Catalogue public
/evenements/mes-evenements/	Liste (organisateur)
/evenements/creer/	Création
/evenements/<slug>/modifier/	Modification
/evenements/<slug>/supprimer/	Annulation (si ventes) ou suppression
/evenements/<slug>/agents-scanner/	Assignation agents
6.4 Scanner (web)
URL	Rôle
/scanner/	Interface classique
/scanner/evenement/<id>/	Interface de scan d'un événement
/scanner/app/	PWA scanner (offline-capable)
/scanner/app/sw.js	Service Worker
/scanner/app/manifest.json	Manifest PWA
6.5 Dashboard
URL	Rôle
/dashboard/	Accueil organisateur
/dashboard/wallet/	Wallet + historique
/dashboard/wallet/reverser/	Demande de retrait
/dashboard/commandes-physiques/	Livraisons à faire
/dashboard/transactions/	Back-office financier (staff)
/dashboard/audit/	Journal d'audit
/dashboard/export/csv/	Export global CSV
/dashboard/export/excel/	Export global Excel
/dashboard/export/pdf/	Export global PDF
6.6 Admin plateforme
URL	Rôle
/admin/	Django admin
/admin/bceao-report/	Rapport financier BCEAO
/admin/export/csv/, /admin/export/excel/	Exports globaux
/api/schema/	OpenAPI schema (staff)
/api/docs/	Swagger UI (staff)
6.7 Notifications (guest)
URL	Rôle
/compte/mes-commandes/	Historique commandes
/compte/facture/<order_type>/<order_number>/	Facture PDF
7. Gestion des erreurs
7.1 Format de réponse erreur
json
{
  "result": "invalid_qr",
  "message": "QR Code invalide",
  "color": "red"
}
7.2 Status HTTP utilisés
Code	Signification
200	Succès (ou résultat métier dans le body)
400	Payload invalide
401	Non authentifié
403	Non autorisé (rôle ou événement)
404	Ressource inexistante
500	Erreur serveur (loggée Sentry)
7.3 Webhooks
Les webhooks PayDunya retournent toujours 200 sauf signature invalide (403). Cela évite les retries infinis côté PayDunya pour des cas déjà traités.

8. Points d'attention
Auth scanner PWA : session cookie, pas JWT. Ne pas mélanger.

CSRF : requis sur tous les POST authentifiés par session. Les webhooks PayDunya sont @csrf_exempt mais vérifient la signature.

Idempotence : client_uuid (scanner sync) + paydunya_token (paiements) — toujours vérifier avant de créer.

Rate limiting : 30/min sur les webhooks, 60/min sur le scan.

Vérification serveur-à-serveur : obligatoire pour tout paiement, jamais de confiance aveugle au webhook.
