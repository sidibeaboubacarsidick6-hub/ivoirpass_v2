# Workflow d'annulation d'événement — Cas inhabituel n°2

## Contexte

Un organisateur peut vouloir annuler un événement **dont les ventes ont
déjà été retirées** de son wallet. Dans ce cas, l'argent n'est plus
disponible chez IvoirPass pour rembourser les acheteurs. La
responsabilité financière revient à l'organisateur.

Pour éviter les abus et tracer les décisions, l'annulation suit un
**workflow en 2 étapes** : l'organisateur fait une demande, un admin
la valide ou la refuse.

## Vue d'ensemble
┌────────────────────────────────────────────────────────────┐
│ Organisateur clique "Annuler" │
│ depuis /evenements/mes-evenements/ │
└─────────────────────┬──────────────────────────────────────┘
│
▼
┌───────────────┐
│ event_delete │ ← Calcule l'impact via
│ (vue Django) │ get_cancellation_impact()
└───────┬───────┘
│
┌─────────────┴─────────────┐
│ │
▼ ▼
Wallet OK Wallet insuffisant
(ventes = 0 (shortfall > 0)
OU solde ≥ ventes)
│ │
▼ ▼
Annulation Redirection vers
immédiate page de confirmation
(comportement │
actuel) ▼
┌─────────────────┐
│ cancel_confirm │
│ (formulaire) │
└────────┬────────┘
│
▼
Statut = CANCEL_PENDING

notif admins
│
▼
┌─────────────────┐
│ Admin Django │
│ approuve ou │
│ refuse │
└────┬───────┬────┘
│ │
▼ ▼
CANCELLED PUBLISHED
(annulation) (retour actif)

text

## Acteurs et responsabilités

### Organisateur
- Peut annuler ses propres événements **uniquement** s'ils ont peu ou pas de ventes retirées
- Pour un événement à wallet insuffisant, il doit :
  1. Lire et accepter une clause de responsabilité
  2. Remplir éventuellement une raison
  3. Attendre la décision d'un admin

### Admin IvoirPass
- Voit les demandes dans `/admin/events/event/`
- Badge orange 🚨 sur les événements en attente
- Actions disponibles :
  - **Valider la demande d'annulation** → annulation effective
  - **Refuser la demande d'annulation** → l'événement redevient publié

### Système
- Notifie les admins à chaque nouvelle demande
- Notifie l'organisateur de la décision (validée/refusée)
- Écrit dans le `AuditLog` chaque action sensible
- Bloque l'annulation si un **litige est en cours** (Cas n°1)

## Détail des états

| Statut | Description | Visible publiquement |
|--------|-------------|:---:|
| `draft` | Brouillon | ❌ |
| `published` | Publié, en vente | ✅ |
| `cancel_pending` | 🚨 Demande d'annulation en attente | ❌ |
| `cancelled` | Annulé (définitif) | ❌ |
| `completed` | Terminé | ❌ |
| `postponed` | Reporté | ✅ |

**Note :** un événement en `cancel_pending` reste invisible
publiquement, mais **n'est pas encore annulé**. Les ventes continuent
d'être bloquées (le `is_on_sale` retourne False car le statut n'est plus
`PUBLISHED`).

## Procédure côté admin

### Valider une demande

1. Aller dans `/admin/events/event/`
2. Filtrer par statut `Annulation en attente`
3. Sélectionner le(s) événement(s)
4. Action : **"✅ Valider la demande d'annulation"**

**Effets automatiques :**
- Annulation complète de l'événement (`cancel_event_organizer_liable`)
- Billets → VOID
- Commandes → CANCELLED
- Wallet → gelé si ventes existaient
- Email à tous les acheteurs (annulation)
- Email à l'organisateur (validation)
- Entrée dans l'AuditLog

### Refuser une demande

1. Aller dans `/admin/events/event/`
2. Sélectionner le(s) événement(s) en `cancel_pending`
3. Action : **"🚫 Refuser la demande d'annulation"**

**Effets automatiques :**
- Statut remis à `PUBLISHED`
- Champs de demande effacés (date, demandeur, raison)
- Email à l'organisateur (refus + raison)
- Entrée dans l'AuditLog

## Ce qui NE change PAS

Le comportement **classique** d'annulation reste identique :

- **0 vente** → suppression définitive
- **Ventes, wallet OK** → annulation immédiate (workflow actuel)

Le nouveau workflow ne s'active **que** dans le cas où le wallet ne peut
pas couvrir les remboursements.

## Fichiers concernés

| Fichier | Rôle |
|---------|------|
| `apps/events/models.py` | Statut `CANCEL_PENDING` + 3 champs `cancel_requested_*` |
| `apps/events/services.py` | `get_cancellation_impact()` + `cancel_event_organizer_liable()` |
| `apps/events/views.py` | `event_delete()` (redirection) + `event_cancel_confirm()` |
| `apps/events/urls.py` | Route `/evenements/<slug>/annuler-confirmer/` |
| `apps/events/admin.py` | Actions `approve_cancellation` / `refuse_cancellation` |
| `templates/events/cancel_confirm.html` | Page de confirmation organisateur |
| `tests/test_event_cancel_workflow.py` | 10 tests unitaires |

## Évolutions futures possibles

- Bouton "Retirer ma demande" côté organisateur (v2)
- Délai automatique de refus après N jours (v2)
- Notification SMS en complément d'email (v2)

**Fin du document.**
