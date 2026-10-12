markdown
# Basculer entre PayDunya et CinetPay

## Principe

Le provider de paiement actif est déterminé par la variable
d'environnement `PAYMENT_PROVIDER`.

Valeurs possibles :
- `paydunya` (défaut)
- `cinetpay` (à venir)

Aucune modification de code n'est nécessaire pour basculer.

## Périmètre — Ce qui bascule et ce qui ne bascule pas

| Fonctionnalité | Bascule possible | Raison |
|----------------|:---:|--------|
| Payin (création facture, webhook, vérification) | ✅ Oui | Dispatcher en place |
| Payout (reversements, PER) | ❌ Non | CinetPay n'a pas d'API payout SDK Python |

**Conséquence :** le payout reste spécifiquement connecté à PayDunya
dans `apps/dashboard/views.py` et `apps/dashboard/tasks.py`. Si un
jour tu bascules entièrement sur CinetPay et que tu veux y faire les
reversements, il faudra coder une intégration payout CinetPay dédiée
(API Transfert REST, pas SDK).

## Comment basculer

### 1. Modifier le `.env` concerné

**Sur preprod** : `/home/ubuntu/apps/preprod-ivoirpass/.env.preprod`
**Sur prod** : `/home/ubuntu/apps/prod-ivoirpass/.env`

Ajouter ou modifier la ligne :
```bash
PAYMENT_PROVIDER=cinetpay
2. S'assurer que les clés du provider cible sont présentes
Pour CinetPay (à ajouter dans .env le jour J) :

bash
CINETPAY_API_KEY=
CINETPAY_SITE_ID=
3. Redémarrer les containers concernés
bash
cd ~/apps/preprod-ivoirpass
docker compose -f docker-compose.preprod.yml restart web celery celery-beat
4. Vérifier
bash
docker compose -f docker-compose.preprod.yml exec web python -c "
import django; django.setup()
from apps.payments.provider import get_provider_name, get_payment_service
print('Provider actif :', get_provider_name())
print('Service :', get_payment_service().__name__)
"
Attendu :

text
Provider actif : cinetpay
Service : CinetPayService
Rollback
Pour revenir à PayDunya :

bash
# 1. Remettre dans .env
PAYMENT_PROVIDER=paydunya

# 2. Redémarrer
docker compose -f docker-compose.preprod.yml restart web celery celery-beat
Notes importantes
Aucun redémarrage de la DB n'est nécessaire.

Aucun rebuild Docker n'est nécessaire (sauf si les dépendances
Python changent — ce sera le cas pour CinetPay : ajouter le SDK
au requirements.txt).

Les transactions en cours ne sont pas affectées : elles
continuent d'utiliser le provider qui les a initiées (un token
PayDunya reste valide pour vérifier un paiement initié avant le
switch).

Toujours tester en mode sandbox avant de basculer en live.

Architecture
text
apps/payments/
├── provider.py           ← Dispatcher : get_payment_service()
├── paydunya.py           ← Service PayDunya (payin + payout)
├── cinetpay.py           ← Service CinetPay (payin seulement, à créer)
├── verification.py       ← Vérif montant + binding (dispatcher-agnostique)
├── views.py              ← Utilise get_payment_service()
└── tasks.py              ← Utilise get_payment_service()

apps/tickets/views.py     ← guest_webhook : dispatcher
apps/store/views.py       ← store_webhook + guest_store_webhook : dispatcher

apps/dashboard/views.py   ← Payout PayDunya en direct (non basculable)
apps/dashboard/tasks.py   ← Payout PayDunya en direct (non basculable)
Prochaine étape (quand CinetPay sera disponible)
Créer apps/payments/cinetpay.py avec les mêmes méthodes que
PayDunyaService :

verify_webhook_signature(request)

create_invoice(order, request)

verify_payment(token)

Le dispatcher le prendra automatiquement en charge dès qu'il sera
importable et que PAYMENT_PROVIDER=cinetpay.

text

**Sauvegarder.**

---

**Exécute le commit, colle-moi le `git log --oneline -4` et le contenu actuel de `docs/bascule-provider.md`.** Ensuite on finit : commit doc + push branche.
