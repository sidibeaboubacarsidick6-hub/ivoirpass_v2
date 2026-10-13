# Bascule PayDunya test → live — Notes et pièges

**Date :** 13 octobre 2026
**Contexte :** passage de PayDunya du mode test au mode live sur
preprod, puis préparation pour la production.

---

## 1. Différences test / live chez PayDunya

| Élément | Test (sandbox) | Live (production) |
|---------|----------------|-------------------|
| **URL API** | `sandbox-api.paydunya.com` | `api.paydunya.com` |
| **Clé principale** | La même | La même |
| **Clé privée** | `test_private_...` | `live_private_...` |
| **Token** | Token test | Token live |
| **Montant minimum** | Aucun | **200 FCFA** |
| **Protection Cloudflare** | Faible | **Stricte** |

**Point critique :** la clé principale est **identique** en test et en live.
Seules la **clé privée** et le **token** changent.

---

## 2. Piège n°1 — Cloudflare bloque les IPs datacenter

### Symptôme
`HTTP 403` avec une page **"Attention Required! | Cloudflare"**.

### Cause
Cloudflare (pare-feu de PayDunya) bloque les requêtes provenant
d'IPs datacenter (VPS, cloud) **qui n'envoient pas de User-Agent**.

### Solution
Ajouter dans **tous** les appels API :
```python
headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'IvoirPass/1.0 (+https://ivoirpass.com)',
    ...
}
Vérification rapide
bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST "https://app.paydunya.com/api/v1/checkout-invoice/create" \
  -H "Content-Type: application/json" \
  -H "User-Agent: IvoirPass/1.0 (+https://ivoirpass.com)" \
  -d '{"invoice":{"total_amount":200,"description":"test"},"store":{"name":"Test"}}'
200 ou 400 ou 1001 → API joignable

403 → Cloudflare bloque (vérifier l'IP ou le User-Agent)

3. Piège n°2 — Caractères cyrilliques dans les clés
Symptôme
text
UnicodeEncodeError: 'latin-1' codec can't encode character '\u0440'
Ou :

text
{"response_code":"1001","response_text":"Invalid Masterkey Specified"}
Cause
Le copier-coller depuis le dashboard PayDunya introduit parfois des
caractères cyrilliques qui ressemblent visuellement aux lettres
latines (р russe au lieu de p, Ø au lieu de 0, etc.).

Détection
python
for name, val in [('MASTER', settings.PAYDUNYA_MASTER_KEY),
                  ('PRIVATE', settings.PAYDUNYA_PRIVATE_KEY),
                  ('TOKEN', settings.PAYDUNYA_TOKEN)]:
    bad = [(i, hex(ord(c))) for i, c in enumerate(val) if ord(c) > 127]
    print(f'{name}: longueur={len(val)}, suspects={bad}')
Attendu : suspects=[] sur les 3.

Solution
Utiliser le bouton "Copier" du dashboard (pas de sélection manuelle)

Passer par Notepad Windows d'abord (neutralise les caractères)

Vérifier visuellement chaque caractère ambigu (0 vs O, 1 vs l, p vs р)

Nettoyer le .env : sed -i 's/\r$//; s/[[:space:]]*$//' .env.preprod

4. Piège n°3 — Montant minimum 200 FCFA en live
Symptôme
text
{"response_code":"4003","response_text":"Invalid Total Amount. Minimum checkout amount is 200 FCFA."}
Cause
PayDunya refuse tout montant strictement inférieur à 200 FCFA en mode live.
Le mode test accepte tout.

Solution
Interception dans create_invoice() (déjà implémenté) :

python
PAYDUNYA_MIN_AMOUNT_LIVE = 200
if settings.PAYDUNYA_MODE == 'live':
    if int(order.total) < PAYDUNYA_MIN_AMOUNT_LIVE:
        return {
            'success': False,
            'error': f"Le montant minimum de paiement est de {PAYDUNYA_MIN_AMOUNT_LIVE} FCFA.",
        }
5. Procédure de bascule test → live
Étape 1 — Backup du .env.preprod actuel
bash
cp .env.preprod .env.preprod.backup-$(date +%Y%m%d-%H%M%S)
Étape 2 — Modifier les 4 valeurs clés
Dans .env.preprod :

text
PAYDUNYA_MODE=live
PAYDUNYA_MASTER_KEY=<clé_principale_identique>
PAYDUNYA_PRIVATE_KEY=live_private_...
PAYDUNYA_TOKEN=<token_live>
PAYDUNYA_BASE_URL=https://prepod.ivoirpass.com
Étape 3 — Nettoyer le fichier
bash
sed -i 's/\r$//; s/[[:space:]]*$//' .env.preprod
Étape 4 — Redémarrer et vérifier
bash
docker compose -f docker-compose.preprod.yml up -d --force-recreate web celery celery-beat

# Vérifier les 3 clés
docker compose -f docker-compose.preprod.yml exec web python -c "
import django; django.setup()
from django.conf import settings
for name, val in [('MASTER', settings.PAYDUNYA_MASTER_KEY),
                  ('PRIVATE', settings.PAYDUNYA_PRIVATE_KEY),
                  ('TOKEN', settings.PAYDUNYA_TOKEN)]:
    print(f'{name}: longueur={len(val)}, suspects={[(i, hex(ord(c))) for i, c in enumerate(val) if ord(c) > 127]}')
"
Étape 5 — Test API live (obligatoire avant tout vrai paiement)
bash
docker compose -f docker-compose.preprod.yml exec web python -c "
import django; django.setup()
import requests
from django.conf import settings
r = requests.post(
    settings.PAYDUNYA_API_BASE + '/checkout-invoice/create',
    json={'invoice': {'total_amount': 200, 'description': 'test'}, 'store': {'name': 'Test'}},
    headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'IvoirPass/1.0 (+https://ivoirpass.com)',
        'PAYDUNYA-MASTER-KEY': settings.PAYDUNYA_MASTER_KEY,
        'PAYDUNYA-PRIVATE-KEY': settings.PAYDUNYA_PRIVATE_KEY,
        'PAYDUNYA-TOKEN': settings.PAYDUNYA_TOKEN,
    },
    timeout=15,
)
print('HTTP :', r.status_code)
print('Réponse :', r.text[:300])
"
Attendu : {"response_code":"00","token":"...","response_text":"https://payment.paydunya.com/..."}

Étape 6 — Test réel 200 FCFA (une fois prêt)
Un vrai paiement avec validation par SMS + réception du billet.
À faire une seule fois avant l'ouverture au public.

6. En cas de problème — Rollback
bash
cd ~/apps/preprod-ivoirpass
cp .env.preprod.backup-<timestamp> .env.preprod
docker compose -f docker-compose.preprod.yml up -d --force-recreate web celery celery-beat
Vérifier que MODE : test est bien revenu.

7. Fichiers concernés
Fichier	Rôle
apps/payments/paydunya.py	Service PayDunya (patched User-Agent + min amount + _safe_json)
apps/payments/cinetpay.py	Service CinetPay (patched préventivement)
.env.preprod (VPS)	Contient les clés live
.env.prod (VPS prod)	À créer — mêmes clés ou nouvelles
