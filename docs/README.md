# Documentation IvoirPass V2

**Index de la documentation technique et fonctionnelle.**
Développé par MKS Soft Technologies — Abidjan, Côte d'Ivoire.

---

## 🎯 À qui s'adresse cette doc

| Public | Point d'entrée |
|---|---|
| **Nouveau dev** | [01-architecture.md](01-architecture.md) puis [02-modele-donnees.md](02-modele-donnees.md) |
| **Dev front** | [01-architecture.md](01-architecture.md) + [06-api.md](06-api.md) |
| **Dev ops** | [05-deploiement.md](05-deploiement.md) |
| **Product / client** | [08-cahier-des-charges-v2.md](08-cahier-des-charges-v2.md) |
| **Maintenance** | [07-changelog.md](07-changelog.md) |

---

## 📚 Sommaire

### Documentation technique

| Fichier | Contenu |
|---|---|
| [01-architecture.md](01-architecture.md) | Stack, structure apps, flux haut niveau |
| [02-modele-donnees.md](02-modele-donnees.md) | Modèles Django, relations, migrations |
| [03-flux-metier.md](03-flux-metier.md) | Billetterie, boutique, KYC, paiements, annulation |
| [04-securite.md](04-securite.md) | Auth, permissions, KYC, ratelimit, HMAC QR |
| [05-deploiement.md](05-deploiement.md) | Docker preprod/prod, migrations, collectstatic, SW |
| [06-api.md](06-api.md) | Endpoints internes, JWT, payloads |
| [07-changelog.md](07-changelog.md) | Historique des chantiers (2026) |

### Documents fonctionnels

| Fichier | Contenu |
|---|---|
| [08-cahier-des-charges-v2.md](08-cahier-des-charges-v2.md) | Cahier des charges client (langage non-technique) |

---

## 🔧 Quickstart dev

Voir le [README.md](../README.md) à la racine pour l'installation locale.

---

## 📖 Règles de lecture

- **Ce qui est verrouillé** : décisions marquées ✅ avec date + contexte
- **Ce qui est reporté** : marqué ⏭️ avec raison et lien
- **Ce qui est legacy** : marqué 🏛️ avec avertissement "ne pas supprimer"

---

## 📅 Dernière mise à jour

2026-09-27 — Documentation initiale après les chantiers boutique + audit.