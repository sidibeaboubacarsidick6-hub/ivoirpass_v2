"""
IvoirPass V2 — Sitemaps SEO
"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from apps.events.models import Event


class EventSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return Event.objects.filter(status=Event.Status.PUBLISHED)

    def lastmod(self, obj):
        return obj.published_at

    def location(self, obj):
        return reverse('events:detail', kwargs={'slug': obj.slug})


class StaticViewSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        # Ajoutez ici les noms de vues statiques publiques que vous voulez
        # indexer, ex: 'accounts:home' pour la page d'accueil
        return ['accounts:home']

    def location(self, item):
        return reverse(item)
