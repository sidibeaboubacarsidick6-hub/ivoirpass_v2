"""
Cache LocMem étendu avec un delete_pattern() no-op, uniquement pour permettre
aux tests de s'exécuter sans dépendre d'un vrai serveur Redis.
Le vrai bug (dépendance dure à django-redis dans apps/events/signals.py,
sans garde-fou si le cache backend ne supporte pas delete_pattern) est
signalé séparément dans le rapport d'audit — ce shim ne le corrige pas,
il permet seulement de tester le reste sans être bloqué par lui.
"""
from django.core.cache.backends.locmem import LocMemCache


class ShimCache(LocMemCache):
    def delete_pattern(self, pattern, **kwargs):
        # No-op : LocMemCache n'indexe pas par pattern, on vide tout par simplicité de test
        self.clear()
