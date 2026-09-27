
- Signature calculée côté serveur avec une clé dérivée de `SECRET_KEY`
- Vérifiée à chaque scan via `ticket.verify_qr(qr_data)`
- Un QR falsifié → `INVALID_QR` (refusé)

### 5.2 Scan offline

Le client ne peut **PAS** vérifier la signature HMAC (pas de clé). Validation locale sur `uuid + ticket_number` uniquement, puis revérification serveur au moment du sync.

Risque accepté (décision 2026-09-27) : l'agent est authentifié, et les QR falsifiés sont détectés au sync.

### 5.3 Invalidation après usage

- `Ticket.status = 'used'` + `scanned_at` renseignés
- Un 2e scan → `ALREADY_USED` (refusé)
- Statut `void` → `TICKET_VOID` (billet annulé)

---

## 6. Sécurité des paiements

### 6.1 Aucune carte bancaire stockée

Le numéro de carte n'est **jamais** transmis à IvoirPass. PayDunya héberge le formulaire de paiement.

### 6.2 Traçabilité BCEAO

- Chaque `Payment` conserve : `paydunya_token`, `raw_response`, timestamps
- Les montants ne sont **jamais** modifiés après création
- Les commandes `PAID` sont immuables (sauf annulation → `CANCELLED`)
- **Rapport BCEAO** exportable via `/admin/bceao-report/`

### 6.3 Idempotence paiement

- `Payment` créée UNE fois par commande (à l'initiation)
- Mise à jour au webhook/retour → `COMPLETED` si confirmé
- Webhook rejoué → détecté, aucun doublon

---

## 7. Sécurité des fichiers

### 7.1 Validateurs d'upload

Chaque type de fichier a une **liste blanche d'extensions** et une **taille maximale** :

| Type | Extensions | Max |
|---|---|---|
| Audio | mp3, wav, flac, m4a, aac, ogg | 200 Mo |
| Vidéo | mp4, mov, webm | 1 Go |
| Livre | pdf, epub | 100 Mo |
| Image | jpg, jpeg, png, webp | 10 Mo |
| Archive | zip | 500 Mo |
| Aperçu | pdf, mp3, jpg, jpeg, png | 20 Mo |
| Cover | jpg, jpeg, png, webp | 5 Mo |

**Règle Django** : `FileExtensionValidator` attend des extensions **sans point** (`['png']`, pas `['.png']`). Respecté via `django_file_extensions()`.

### 7.2 Fichiers numériques (boutique)

- Stockés dans `media/store/digital/`
- Accessibles uniquement après paiement via token temporaire (`GuestDownloadLink.token`)
- Lien expirant (48h par défaut) + limite de téléchargements (3 par défaut)
- Aucun accès direct par URL statique

### 7.3 Watermark

- **PDF** : filigrane texte (nom acheteur + n° commande) via ReportLab
- **EPUB/MOBI** : métadonnées injectées dans le `.opf`
- **MP3** : ⏭️ non implémenté (complexité ré-encodage ID3) — documenté dans `apps/store/watermark.py`

---

## 8. Sécurité du scanner PWA

### 8.1 Service Worker

- Fichier servi par vue Django dédiée (`serve_service_worker`)
- **Scope strict** : `/scanner/app/` (via header `Service-Worker-Allowed`)
- **`Cache-Control: no-cache`** → mises à jour immédiates

### 8.2 Stockage local (IndexedDB)

Décision 2026-09-27 : **stockage en clair**, purge automatique à la déconnexion.

- Contient : `uuid`, `ticket_number`, `ticket_type`, `buyer_name`, `qr_data`
- Ces données sont déjà imprimées sur le billet physique → risque faible
- Chiffrement AES-GCM reporté (chantier dédié si nécessaire)

### 8.3 Autorisation par événement

Chaque appel API scanner vérifie (`_authorize_agent_for_event`) :
- Admin → tout
- Organisateur → ses événements uniquement
- Agent scanner → événements assignés (`Event.scanner_agents`) uniquement

---

## 9. Sécurité infrastructure

### 9.1 Docker preprod/prod

- Base de données **non exposée** à l'extérieur (pas de `ports:`)
- Redis **non exposé**
- Web en `127.0.0.1:8100` — accessible uniquement via Nginx
- Nginx en reverse proxy + SSL Let's Encrypt

### 9.2 Variables d'environnement

`.env.preprod` / `.env` — **jamais commités** (vérifié dans `.gitignore` et CI).

Contient : `SECRET_KEY`, `DB_PASSWORD`, `PAYDUNYA_*`, `EMAIL_*`.

### 9.3 Sécurité CI

GitHub Actions vérifie à chaque push :
- Aucun `.env` ou `.sql` commité dans l'historique
- Tests passent
- Migrations cohérentes

### 9.4 Monitoring

- **Sentry** : capture des exceptions + alertes
- **AuditLog** : journal interne des actions sensibles
- **Celery Beat** : surveillance automatique des paiements PENDING

---

## 10. Points d'attention

### 🏛️ Legacy à surveiller

- `ProductOrder` / `DownloadLink` : ne pas supprimer (BCEAO, exports)
- Tunnels "avec compte" désactivés mais code conservé — ne pas réactiver sans audit

### ⚠️ Pièges connus

- **Fichiers statiques** : `collectstatic` obligatoire après modif de `static/`
- **Service Worker** : bump `CACHE_NAME` si `index.html` change
- **CSRF** : régénéré après login — rechargement complet nécessaire côté PWA scanner
- **`is_organizer_verified`** : BooleanField dédié, pas dérivé de `kyc_verified_at`

### 🚨 À ne jamais faire

- Supprimer un `Event` avec commandes `PAID` (cascade → perte traçabilité BCEAO)
- Supprimer un `Product` avec ventes (idem)
- Désactiver la vérification serveur-à-serveur PayDunya
- Commiter un `.env` ou un dump SQL

---

## 📅 Dernière mise à jour

2026-09-27 — Documentation initiale.