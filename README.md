# IvoirPass V2

**Plateforme ivoirienne de billetterie et de distribution culturelle**
Développé par MKS Soft Technologies — Abidjan, Côte d'Ivoire

---

## Stack technique

| Composant        | Technologie                    |
|-------------------|---------------------------------|
| Backend           | Django 4.2 + DRF               |
| Base de données   | PostgreSQL                     |
| Cache             | Redis                          |
| Frontend          | Bootstrap 5 + Alpine.js        |
| Scanner mobile    | PWA HTML/JS (intégrée au site) |
| Authentification API | JWT (rest_framework_simplejwt) |
| Paiement          | PayDunya (Wave, OM, MTN)       |
| PDF               | ReportLab                      |
| QR Code           | qrcode + html5-qrcode          |
| Email             | SMTP / Console (dev)           |
| Déploiement       | OVH Ubuntu + Nginx + Gunicorn  |

---

## Installation locale

### Prérequis
- Python 3.12+
- PostgreSQL 14+
- Redis
- ngrok (pour webhooks PayDunya et démonstrations en dev)

### Étapes

```bash
# 1. Cloner le projet
git clone https://github.com/sidibeaboubacarsidick6-hub/ivoirpass_v2.git
cd ivoirpass_v2

# 2. Environnement virtuel
python3 -m venv venv
source venv/bin/activate

# 3. Dépendances
pip install -r requirements.txt

# 4. Variables d'environnement
cp .env.example .env
# Remplir les variables dans .env

# 5. Base de données
createdb ivoirpass_db
python manage.py migrate

# 6. Superutilisateur
python manage.py createsuperuser

# 7. Données initiales
python manage.py shell -c "
from apps.events.models import Category
cats = [
  ('concerts',     'bi-music-note-beamed', '#E91E63'),
  ('Cinéma',      'bi-camera-reels',      '#9C27B0'),
  ('Sport',       'bi-trophy',            '#FF5722'),
  ('Théâtre',     'bi-masks',             '#3F51B5'),
  ('Festival',    'bi-stars',             '#F47920'),
  ('Conférence',  'bi-mic',              '#1B7A3E'),
]
for name, icon, color in cats:
    Category.objects.get_or_create(
        name=name,
        defaults={'icon': icon, 'color': color}
    )
print('Catégories créées ✅')
"

# 8. Lancer (un seul serveur, y compris pour le scanner — voir plus bas)
python manage.py runserver
```

**Pour une démo/présentation avec un tunnel public**, un seul ngrok suffit :
```bash
ngrok http 8000
```
Le site principal ET l'application de scan sont servis par le même serveur — pas besoin d'un deuxième terminal ni d'un deuxième tunnel.

---

## Structure du projet

```
ivoirpass_v2/
├── config/                  # Configuration Django
│   ├── settings/
│   │   ├── base.py          # Settings communs
│   │   ├── development.py   # Dev local
│   │   ├── production.py    # OVH production
│   │   └── testlocal.py     # Tests isolés (SQLite, Celery eager, email locmem)
│   └── urls.py               # URLs principales
│
├── apps/
│   ├── accounts/             # Utilisateurs & authentification (+ API JWT)
│   ├── events/                # Événements
│   ├── tickets/                # Billetterie & QR Code
│   ├── payments/               # Intégration PayDunya
│   ├── dashboard/               # Dashboard organisateur, Wallet & rapports admin
│   ├── scanner/                  # Scanner QR Code (web ET application mobile)
│   │   └── api/                   # API JWT pour l'application de scan
│   ├── store/                      # Boutique culturelle
│   └── notifications/               # Email & SMS
│
├── templates/
│   └── scanner_app/                  # Application de scan (PWA), servie par Django
├── static/                            # CSS, JS, images
├── media/                              # Fichiers uploadés
└── tests/                               # Tests unitaires
```

---

## Rôles utilisateurs

| Rôle        | Accès                                                  |
|-------------|----------------------------------------------------------|
| *(aucun rôle spécial)* | Acheter des billets, boutique, voir ses billets |
| organizer   | Créer événements, gérer boutique, wallet, scanner ses propres événements |
| scanner     | Scanner le QR Code de n'importe quel événement publié (web ou application) |
| admin       | Administration complète, rapports BCEAO, exports         |

Les comptes `scanner` et `admin` se créent aujourd'hui manuellement via `/admin/` (pas encore d'auto-inscription pour ce rôle — voir GUIDE_UTILISATEUR.md).

---

## URLs principales

| URL                              | Description                          |
|-----------------------------------|----------------------------------------|
| `/`                                | Page d'accueil                        |
| `/evenements/`                      | Liste des événements                  |
| `/evenements/creer/`                 | Créer un événement                    |
| `/billets/panier/`                    | Panier billetterie                    |
| `/billets/mes-billets/`                | Mes billets                           |
| `/boutique/`                            | Boutique culturelle                   |
| `/boutique/mes-produits/`                | Gestion produits vendeur              |
| `/boutique/mes-commandes/`                | Mes commandes boutique                |
| `/dashboard/`                              | Dashboard organisateur                |
| `/dashboard/wallet/`                        | Wallet & reversements                 |
| `/scanner/`                                  | Interface de scan QR (navigateur)     |
| `/scanner/app/`                               | **Application de scan** (PWA, plein écran, optimisée mobile) |
| `/admin/`                                      | Administration Django                 |
| `/admin/bceao-report/`                          | Rapport financier BCEAO (réservé staff) |
| `/admin/export/csv/`, `/admin/export/excel/`     | Exports admin (réservés staff)        |
| `/api/accounts/token/`                            | Obtenir un token JWT (email + mot de passe) |
| `/api/accounts/token/refresh/`                     | Rafraîchir un token JWT expiré        |
| `/api/scanner/my-events/`                           | Liste des événements scannables par l'agent connecté |
| `/api/scanner/scan/`                                 | Scanner un QR code (JWT requis)      |

---

## Scanner : deux façons de scanner, un seul système derrière

- **`/scanner/`** : interface classique dans le navigateur, avec session Django habituelle (cookie de connexion). Pratique pour un usage ponctuel depuis un ordinateur ou un téléphone.
- **`/scanner/app/`** : application plein écran optimisée mobile (PWA), avec sa propre authentification par token JWT — pensée pour un usage intensif terrain par plusieurs agents en même temps.

Les deux passent par la même vérification côté serveur (signature du billet, verrou anti-double-scan, appartenance à l'événement) — aucune des deux n'est "moins sécurisée" que l'autre.

---

## Flux de paiement

Client → Panier → Checkout → PayDunya
→ PayDunya → Webhook → Vérification serveur-à-serveur → Confirmation
→ Génération tickets / liens téléchargement
→ Email notification (billet PDF en pièce jointe)
→ Wallet organisateur crédité (net après commission)

---

## Système de commission

- Commission **prélevée sur l'organisateur**, jamais sur l'acheteur
- Taux **configurable par événement** (défaut 8%)
- Défini par l'admin au moment de la validation
- Visible dans le dashboard organisateur

---

## Tests

```bash
DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests --verbosity=2
DJANGO_SETTINGS_MODULE=config.settings.testlocal coverage run --source='apps' manage.py test tests
coverage report
```

`config/settings/testlocal.py` isole les tests (SQLite en mémoire, Celery synchrone, email en mémoire) — aucune dépendance à Postgres/Redis pour lancer la suite.

---

## Sécurité — points déjà traités

- Vérification serveur-à-serveur des paiements PayDunya (pas de confiance aveugle au webhook)
- Signature HMAC sur les QR codes des billets
- Verrou anti-double-scan (un billet ne peut pas être validé deux fois même par deux agents simultanés)
- Exports admin et rapport BCEAO réservés au staff
- Authentification par compte individuel (JWT) pour l'application de scan — plus de clé API partagée

---

## Déploiement (à venir)

- Serveur : OVH Ubuntu VPS (ou équivalent)
- Web : Nginx + Gunicorn
- SSL : Let's Encrypt
- DB : PostgreSQL
- Variables critiques à définir en prod : `PAYDUNYA_MODE=live`, `SECRET_KEY` unique, `ALLOWED_HOSTS`
