"""
Tests Vague 4 — Tunnel multi-jours (Étape 1).
"""
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Category, Event


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='O', last_name='G',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


class MultiDayStep1Tests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.client.force_login(self.org)
        self.category = Category.objects.create(
            name='Test', slug='test-multiday',
        )

    def test_get_etape_1_affiche_formulaire(self):
        """L'accès en GET affiche le formulaire."""
        resp = self.client.get(reverse('events:multi_day_step_1'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'multi-jours')

    def test_post_etape_1_cree_event_brouillon(self):
        """Un POST valide crée un event en brouillon + is_multi_day=True."""
        now = timezone.now()
        data = {
            'title': 'Festival Test',
            'category': self.category.pk,
            'description': 'Desc',
            'short_description': '0700000000',
            'event_type': 'physical',
            'start_date': (now + timezone.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M'),
            'end_date': (now + timezone.timedelta(days=32)).strftime('%Y-%m-%dT%H:%M'),
            'venue_city': 'Abidjan',
            'total_capacity': '0',
            'status': 'draft',   # ← OBLIGATOIRE
            # Formsets annexes (vides mais avec management_form)
            'faqs-TOTAL_FORMS': '0',
            'faqs-INITIAL_FORMS': '0',
            'faqs-MIN_NUM_FORMS': '0',
            'faqs-MAX_NUM_FORMS': '1000',
            'gallery_items-TOTAL_FORMS': '0',
            'gallery_items-INITIAL_FORMS': '0',
            'gallery_items-MIN_NUM_FORMS': '0',
            'gallery_items-MAX_NUM_FORMS': '1000',
            'partners-TOTAL_FORMS': '0',
            'partners-INITIAL_FORMS': '0',
            'partners-MIN_NUM_FORMS': '0',
            'partners-MAX_NUM_FORMS': '1000',
        }
        resp = self.client.post(reverse('events:multi_day_step_1'), data)

        # Debug : affiche toutes les erreurs si le POST échoue
        if resp.status_code != 302 and hasattr(resp, 'context') and resp.context:
            form = resp.context.get('form')
            if form and form.errors:
                print("FORM ERRORS:", dict(form.errors))
            for key in ('faq_formset', 'gallery_formset', 'partner_formset'):
                fs = resp.context.get(key)
                if fs and fs.errors:
                    print(f"{key} ERRORS:", fs.errors)

        self.assertEqual(resp.status_code, 302)
        event = Event.objects.filter(organizer=self.org).first()
        self.assertIsNotNone(event)
        self.assertTrue(event.is_multi_day)
        self.assertEqual(event.status, Event.Status.DRAFT)

    def test_utilisateur_non_connecte_redirige_login(self):
        """Sans login → redirigé vers login."""
        self.client.logout()
        resp = self.client.get(reverse('events:multi_day_step_1'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)