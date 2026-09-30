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


class MultiDayStep2Tests(TestCase):
    def setUp(self):
        self.org = _make_organizer()
        self.client.force_login(self.org)
        self.category = Category.objects.create(
            name='Test', slug='test-step2-multiday',
        )
        # Crée un event multi-jours 3 jours
        now = timezone.now()
        self.event = Event.objects.create(
            title='Festival Étape 2',
            slug='festival-etape-2',
            description='d',
            short_description='0700000000',
            category=self.category,
            organizer=self.org,
            start_date=now + timezone.timedelta(days=30),
            end_date=now + timezone.timedelta(days=32),
            status=Event.Status.DRAFT,
            is_multi_day=True,
        )

    def test_get_genere_les_jours_automatiquement(self):
        """GET génère 3 jours depuis les dates si aucun n'existe."""
        self.assertEqual(self.event.event_days.count(), 0)
        resp = self.client.get(
            reverse('events:multi_day_step_2', args=[self.event.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.event.event_days.count(), 3)

    def test_post_enregistre_les_noms(self):
        """POST sauvegarde les jours modifiés (nom personnalisé)."""
        # Pré-génère les jours
        self.event.generate_event_days()
        days = list(self.event.event_days.order_by('date'))
        self.assertEqual(len(days), 3)

        data = {
            'event_days-TOTAL_FORMS': '3',
            'event_days-INITIAL_FORMS': '3',
            'event_days-MIN_NUM_FORMS': '0',
            'event_days-MAX_NUM_FORMS': '1000',
            'event_days-0-id': str(days[0].pk),
            'event_days-0-date': days[0].date.strftime('%Y-%m-%d'),
            'event_days-0-name': 'Soirée d\'ouverture',
            'event_days-0-doors_open': '',
            'event_days-1-id': str(days[1].pk),
            'event_days-1-date': days[1].date.strftime('%Y-%m-%d'),
            'event_days-1-name': '',
            'event_days-1-doors_open': '19:00',
            'event_days-2-id': str(days[2].pk),
            'event_days-2-date': days[2].date.strftime('%Y-%m-%d'),
            'event_days-2-name': 'Finale',
            'event_days-2-doors_open': '',
        }
        resp = self.client.post(
            reverse('events:multi_day_step_2', args=[self.event.pk]),
            data,
        )
        # Redirection vers étape 3
        self.assertEqual(resp.status_code, 302)
        days[0].refresh_from_db()
        self.assertEqual(days[0].name, 'Soirée d\'ouverture')
        days[1].refresh_from_db()
        self.assertEqual(days[1].doors_open.strftime('%H:%M'), '19:00')

    def test_post_ajoute_un_nouveau_jour(self):
        """POST peut ajouter un 4e jour via le formset."""
        self.event.generate_event_days()
        days = list(self.event.event_days.order_by('date'))

        data = {
            'event_days-TOTAL_FORMS': '4',
            'event_days-INITIAL_FORMS': '3',
            'event_days-MIN_NUM_FORMS': '0',
            'event_days-MAX_NUM_FORMS': '1000',
            # 3 jours existants
            'event_days-0-id': str(days[0].pk),
            'event_days-0-date': days[0].date.strftime('%Y-%m-%d'),
            'event_days-0-name': '',
            'event_days-0-doors_open': '',
            'event_days-1-id': str(days[1].pk),
            'event_days-1-date': days[1].date.strftime('%Y-%m-%d'),
            'event_days-1-name': '',
            'event_days-1-doors_open': '',
            'event_days-2-id': str(days[2].pk),
            'event_days-2-date': days[2].date.strftime('%Y-%m-%d'),
            'event_days-2-name': '',
            'event_days-2-doors_open': '',
            # 1 nouveau jour
            'event_days-3-date': '2026-12-18',
            'event_days-3-name': 'Bonus',
            'event_days-3-doors_open': '',
        }
        resp = self.client.post(
            reverse('events:multi_day_step_2', args=[self.event.pk]),
            data,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.event.event_days.count(), 4)
        self.assertTrue(
            self.event.event_days.filter(name='Bonus').exists()
        )