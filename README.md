# IvoirPass V2

**Plateforme ivoirienne de billetterie et de distribution culturelle**
Développé par MKS Soft Technologies — Abidjan, Côte d'Ivoire

---

## Stack technique

| Composant     | Technologie              |
|---------------|--------------------------|
| Backend       | Django 4.2 + DRF         |
| Base de données | PostgreSQL             |
| Cache         | Redis                    |
| Frontend      | Bootstrap 5 + Alpine.js  |
| Paiement      | PayDunya (Wave, OM, MTN) |
| PDF           | ReportLab                |
| QR Code       | qrcode + ZXing           |
| Email         | SMTP / Console (dev)     |
| Déploiement   | OVH Ubuntu + Nginx + Gunicorn |

---

## Installation locale

### Prérequis
- Python 3.12+
- PostgreSQL 14+
- Redis
- ngrok (pour webhooks PayDunya en dev)

### Étapes

```bash
# 1. Cloner le projet
git clone https://github.com/mks-soft/ivoirpass.git
cd ivoirpass

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

# 8. Lancer
python manage.py runserver
```

---

## Structure du projet
ivoirpass/

├── config/                  # Configuration Django

│   ├── settings/

│   │   ├── base.py         # Settings communs

│   │   ├── development.py  # Dev local

│   │   └── production.py   # OVH production

│   └── urls.py             # URLs principales

│

├── apps/

│   ├── accounts/           # Utilisateurs & authentification

│   ├── events/             # Événements

│   ├── tickets/            # Billetterie & QR Code

│   ├── payments/           # Intégration PayDunya

│   ├── dashboard/          # Dashboard organisateur & Wallet

│   ├── scanner/            # Scanner QR Code

│   ├── store/              # Boutique culturelle

│   └── notifications/      # Email & SMS

│

├── templates/              # HTML templates Bootstrap 5

├── static/                 # CSS, JS, images

├── media/                  # Fichiers uploadés

└── tests/                  # Tests unitaires

---

## Rôles utilisateurs

| Rôle        | Accès                                    |
|-------------|------------------------------------------|
| participant | Acheter tickets, boutique, voir billets  |
| organizer   | Créer événements, gérer boutique, wallet |
| scanner     | Scanner QR Code à l'entrée              |
| admin       | Administration complète                 |

---

## URLs principales

| URL                          | Description                |
|------------------------------|----------------------------|
| `/`                          | Page d'accueil             |
| `/evenements/`               | Liste des événements       |
| `/evenements/creer/`         | Créer un événement         |
| `/billets/panier/`           | Panier billetterie         |
| `/billets/mes-billets/`      | Mes billets                |
| `/boutique/`                 | Boutique culturelle        |
| `/boutique/mes-produits/`    | Gestion produits vendeur   |
| `/boutique/mes-commandes/`   | Mes commandes boutique     |
| `/dashboard/`                | Dashboard organisateur     |
| `/dashboard/wallet/`         | Wallet & reversements      |
| `/scanner/`                  | Interface de scan QR       |
| `/admin/`                    | Administration Django      |

---

## Flux de paiement
Client → Panier → Checkout → PayDunya

PayDunya → Webhook → Confirmation automatique

→ Génération tickets / liens téléchargement

→ Email notification

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
python manage.py test tests --verbosity=2
coverage run --source='.' manage.py test tests
coverage report
```

---

## Déploiement (Phase 10 — à venir)

- Serveur : OVH Ubuntu VPS
- Web : Nginx + Gunicorn
- SSL : Let's Encrypt
- DB : PostgreSQL
- Process : Systemd