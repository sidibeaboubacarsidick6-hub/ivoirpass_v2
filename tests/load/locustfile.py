"""
Test de charge IvoirPass — scénarios réalistes.

⚠️ Ne PAS lancer contre la prod. Cible : prepod.ivoirpass.com uniquement.

Lancement (depuis le laptop, PAS le VPS) :
    cd ~/ivoirpass
    locust -f tests/load/locustfile.py --host=https://prepod.ivoirpass.com

Puis ouvrir http://localhost:8089 dans le navigateur.

Paliers recommandés :
    1.  50 users (spawn 5/s)  → échauffement
    2. 100 users (spawn 10/s) → validation
    3. 150 users (spawn 15/s) → pic réaliste
    4. 200 users (spawn 20/s) → stress (optionnel)
    5. 300 users (spawn 30/s) → limite (optionnel, ⚠️ lourd)

Arrêter dès que Failures > 5 %.

⚠️ Ce test N'ENVOIE PAS de vrais paiements PayDunya — il s'arrête au
formulaire de checkout (GET uniquement, pas de POST valide).
"""
from locust import HttpUser, task, between, events
import random


# ──────────────────────────────────────────────────────────────
# Slugs d'événements réels en preprod
# ──────────────────────────────────────────────────────────────
EVENT_SLUGS = [
    "invasions-des-ultra",
    "concert-de-noel",
    "evenement-test",
    "octobre-rose-1",
    "la-pensee-positive",
]


# ──────────────────────────────────────────────────────────────
# Utilisateur 1 — Visiteur anonyme (58 % du trafic)
# Navigation classique, sans intention d'achat immédiate.
# ──────────────────────────────────────────────────────────────
class VisiteurAnonyme(HttpUser):
    weight = 58
    wait_time = between(2, 5)

    @task(10)
    def accueil(self):
        self.client.get("/", name="/accueil")

    @task(6)
    def liste_evenements(self):
        self.client.get("/evenements/", name="/evenements")

    @task(2)
    def recherche(self):
        queries = ["concert", "festival", "abidjan", "rap", "afro"]
        q = random.choice(queries)
        self.client.get(f"/evenements/?q={q}", name="/evenements?q=[query]")

    @task(8)
    def detail_evenement(self):
        slug = random.choice(EVENT_SLUGS)
        self.client.get(
            f"/evenements/{slug}/",
            name="/evenements/[slug]",
        )

    @task(3)
    def voir_boutique(self):
        self.client.get("/boutique/", name="/boutique")

    @task(1)
    def page_statique(self):
        self.client.get("/comment-ca-marche/", name="/comment-ca-marche")


# ──────────────────────────────────────────────────────────────
# Utilisateur 2 — Acheteur potentiel (25 % du trafic)
# Va jusqu'au formulaire d'achat MAIS ne soumet pas.
# ──────────────────────────────────────────────────────────────
class AcheteurPotentiel(HttpUser):
    weight = 25
    wait_time = between(3, 8)

    @task(3)
    def consulter_evenement(self):
        slug = random.choice(EVENT_SLUGS)
        self.client.get(
            f"/evenements/{slug}/",
            name="/evenements/[slug]",
        )

    @task(5)
    def page_achat(self):
        slug = random.choice(EVENT_SLUGS)
        self.client.get(
            f"/billets/acheter/{slug}/",
            name="/billets/acheter/[slug]",
        )

    @task(2)
    def revoir_accueil(self):
        self.client.get("/", name="/accueil")


# ──────────────────────────────────────────────────────────────
# Utilisateur 3 — Visiteur mobile (17 % du trafic)
# Mixte navigation + achat, avec User-Agent iPhone.
# ──────────────────────────────────────────────────────────────
class VisiteurMobile(HttpUser):
    weight = 17
    wait_time = between(1, 4)

    def on_start(self):
        self.client.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                'Version/17.0 Mobile/15E148 Safari/604.1'
            )
        })

    @task(4)
    def accueil(self):
        self.client.get("/", name="/accueil [mobile]")

    @task(3)
    def liste_evenements(self):
        self.client.get("/evenements/", name="/evenements [mobile]")

    @task(3)
    def detail_evenement(self):
        slug = random.choice(EVENT_SLUGS)
        self.client.get(
            f"/evenements/{slug}/",
            name="/evenements/[slug] [mobile]",
        )

    @task(2)
    def page_achat(self):
        slug = random.choice(EVENT_SLUGS)
        self.client.get(
            f"/billets/acheter/{slug}/",
            name="/billets/acheter/[slug] [mobile]",
        )


# ──────────────────────────────────────────────────────────────
# Rapport automatique en fin de test
# ──────────────────────────────────────────────────────────────
@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Affiche un résumé lisible à la fin du test."""
    stats = environment.stats
    print("\n" + "=" * 60)
    print("RÉSUMÉ DU TEST DE CHARGE — IvoirPass V2")
    print("=" * 60)
    print(f"Requêtes totales    : {stats.total.num_requests}")
    print(f"Requêtes échouées   : {stats.total.num_failures}")
    print(f"Taux d'erreur       : {stats.total.fail_ratio * 100:.2f}%")
    print(f"Temps médian        : {stats.total.median_response_time} ms")
    print(f"Temps moyen         : {stats.total.avg_response_time:.0f} ms")
    print(f"Pire requête        : {stats.total.max_response_time} ms")
    print(f"Req/s moyennes      : {stats.total.total_rps:.1f}")
    print("-" * 60)

    if stats.total.fail_ratio > 0.05:
        print("⚠️  ATTENTION : plus de 5% d'erreurs — le serveur sature")
        print("   → Arrêter le test et analyser les logs.")
    elif stats.total.fail_ratio > 0.01:
        print("⚠️  Légère dégradation — surveiller les prochains paliers.")
    else:
        print("✅ Tout va bien — aucune saturation détectée.")

    # Seuils de performance
    if stats.total.median_response_time > 1000:
        print("⚠️  Médiane > 1 s → optimisation à prévoir.")
    elif stats.total.median_response_time > 500:
        print("ℹ️  Médiane > 500 ms → acceptable mais à surveiller.")
    else:
        print("✅ Médiane < 500 ms → expérience utilisateur excellente.")

    print("=" * 60 + "\n")