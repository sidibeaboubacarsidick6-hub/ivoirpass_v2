# Vague 4 — Événements multi-jours + Scanner

**Date :** 2026-10-01
**Statut :** ✅ Terminée (Session A + T1 + T2 + T3 + D)

---

## 📋 Vue d'ensemble

Permet à un organisateur de créer un événement **sur plusieurs jours**
avec des **billets / packs** couvrant un ou plusieurs jours. Le scanner
valide **1 scan par jour** pour les pass multi-jours, tandis que les
billets classiques conservent leur comportement (1 scan définitif).

**Principe directeur :** aucune modification du flux normal de création
d'événement. Le multi-jours vit dans un **tunnel dédié** accessible depuis
un bandeau discret sur la page de création standard.

---

## 🗂️ Modèles

### `EventDay` (nouveau — `apps/events/models.py`)

Jour d'un événement multi-jours.

| Champ | Type | Notes |
|---|---|---|
| `event` | FK Event | CASCADE |
| `date` | DateField | Contrainte unique (event, date) |
| `name` | CharField(100) | Optionnel — « Finale », « Soirée d'ouverture » |
| `doors_open` | TimeField | Optionnel |
| `order` | PositiveInteger | Tri d'affichage |

**Propriété** `display_name` : retourne `name` ou la date formatée.

### `TicketType.event_days` (nouveau — M2M)

M2M vers `EventDay`. Vide = billet legacy. Non vide = 1 scan par jour.

### `Event.is_multi_day` (nouveau)

BooleanField default=False. Marqueur indiquant que l'événement a été créé
via le tunnel. **Les événements existants restent à False** → comportement
legacy préservé.

### `TicketType.order` (modifié)

Ajout `blank=True` (permet un POST vide → default=0 appliqué).

### `ScanLog.event_day` (nouveau — `apps/scanner/models.py`)

FK nullable vers `EventDay`. Enregistre le jour concerné par le scan
(uniquement pour les billets multi-jours).

### `ScanLog.guest_ticket` (nouveau)

FK nullable vers `GuestTicket`. Permet de tracer les scans de billets
invités (multi-jours) — sans ce champ, impossible de compter les scans
par jour sur les GuestTicket.

---

## 🔗 URLs

| URL | Vue | Description |
|---|---|---|
| `/evenements/creer-multijour/etape-1/` | `multi_day_step_1` | Infos de base → crée un Event brouillon |
| `/evenements/creer-multijour/etape-2/<id>/` | `multi_day_step_2` | Jours (auto-générés depuis dates) |
| `/evenements/creer-multijour/etape-3/<id>/` | `multi_day_step_3` | Billets + packs + jours couverts |

---

## 🖥️ Tunnel multi-jours (organisateur)

### Étape 1 — Informations de base

**Fichier :** `templates/events/multi_day/step_1.html`

Reprend **tout le formulaire normal** (infos + dates + lieu + médias +
FAQ + galerie + partenaires) — SAUF Types de tickets (déplacés à l'Étape 3).

Champ caché `status=draft` : l'événement est créé en brouillon, publié
à la fin du tunnel.

### Étape 2 — Jours de l'événement

**Fichier :** `templates/events/multi_day/step_2.html`

- Auto-génération : `Event.generate_event_days()` crée 1 EventDay par
  jour entre `start_date` et `end_date` (au premier accès, si aucun
  n'existe)
- L'organisateur peut **renommer** (« Soirée d'ouverture », « Finale »),
  **ajouter** ou **retirer** des jours
- Bouton « ← Retour à l'Étape 1 » : **sauvegarde d'abord** puis redirige
  (action `back` dans le POST)

### Étape 3 — Billets / packs

**Fichier :** `templates/events/multi_day/step_3.html`

- Crée des billets / packs avec cases à cocher pour les jours couverts
- Cases à cocher → M2M `TicketType.event_days`
- 3 boutons finaux :
  - **← Retour à l'Étape 2** (sauvegarde puis redirige)
  - **Enregistrer en brouillon** (reste Draft)
  - **Publier l'événement** (passe Published, vérifie KYC si payant)

---

## 🎫 Scanner (agents + organisateurs)

### Logique de validation

Méthode commune `can_be_scanned_on(target_date)` sur `Ticket` et
`GuestTicket` :

```python
def can_be_scanned_on(self, target_date):
    """
    Retourne (ok, reason, event_day).
    - Billet legacy (pas d'event_days) : ok si status != USED/VOID
    - Multi-jours : ok si target_date correspond à un EventDay
    """