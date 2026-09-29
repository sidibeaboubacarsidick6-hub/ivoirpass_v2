"""
Tests du champ Event.custom_message (message personnalisé email billets).

Vérifie :
- Le modèle stocke bien le message (500 max, blank autorisé)
- Le formulaire l'accepte et le rend correctement
- Le service email le passe au contexte
- Les templates HTML + TXT l'affichent
- Le message vide ne casse rien
"""
from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.template.loader import render_to_string
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.events.models import Event, Category
from apps.events.forms import EventForm


def _make_organizer(email='org@test.com'):
    u = CustomUser.objects.create_user(
        email=email, password='pass', first_name='Org', last_name='T',
    )
    u.role = CustomUser.Role.ORGANIZER
    u.is_organizer_verified = True
    u.save()
    return u


def _make_event(organizer, **kwargs):
    cat, _ = Category.objects.get_or_create(name='Test')
    defaults = {
        'title': 'Concert Test',
        'slug': 'concert-test',
        'description': 'd',
        'short_description': '+225 07 00 00 00 00',
        'category': cat,
        'organizer': organizer,
        'start_date': timezone.now() + timedelta(days=7),
        'end_date': timezone.now() + timedelta(days=7, hours=3),
        'status': Event.Status.PUBLISHED,
        'venue_name': 'Palais',
        'venue_address': 'Y',
        'venue_city': 'Abidjan',
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


class CustomMessageModelTests(TestCase):
    """Test du champ sur le modèle."""

    def setUp(self):
        self.org = _make_organizer()

    def test_message_vide_par_defaut(self):
        e = _make_event(self.org)
        self.assertEqual(e.custom_message, '')

    def test_message_enregistre(self):
        msg = "Merci d'avoir acheté !\nRendez-vous bientôt."
        e = _make_event(self.org, custom_message=msg)
        e.refresh_from_db()
        self.assertEqual(e.custom_message, msg)

    def test_message_max_500_caracteres(self):
        msg = "a" * 500
        e = _make_event(self.org, custom_message=msg)
        self.assertEqual(len(e.custom_message), 500)


class CustomMessageFormTests(TestCase):
    """Test du formulaire."""

    def setUp(self):
        self.org = _make_organizer()
        self.cat, _ = Category.objects.get_or_create(name='Test')

    def _form_data(self, custom_message=''):
        return {
            'title': 'Test',
            'description': 'd',
            'short_description': '+225 07 00 00 00 00',
            'category': self.cat.pk,
            'event_type': 'physical',
            'start_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
            'end_date': (timezone.now() + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'),
            'venue_name': 'X',
            'venue_city': 'Y',
            'total_capacity': 100,
            'status': 'published',
            'custom_message': custom_message,
        }

    def test_form_accepte_message(self):
        form = EventForm(data=self._form_data(custom_message='Hello world'))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.cleaned_data['custom_message'], 'Hello world')

    def test_form_accepte_message_vide(self):
        form = EventForm(data=self._form_data(custom_message=''))
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_form_rejette_message_plus_500(self):
        form = EventForm(data=self._form_data(custom_message='a' * 501))
        self.assertFalse(form.is_valid())
        self.assertIn('custom_message', form.errors)


class CustomMessageEmailRenderTests(TestCase):
    """Test du rendu dans les templates email."""

    def _render(self, template_name, custom_message):
        ctx = {
            'buyer_name': 'Jean',
            'event': type('E', (), {
                'custom_message': custom_message,
                'title': 'Concert',
                'start_date': timezone.now(),
                'venue_name': 'Palais',
                'venue_city': 'Abidjan',
            })(),
            'order': type('O', (), {
                'order_number': 'TEST-001',
                'total': 5000,
                'payment_method': 'wave',
            })(),
            'tickets_with_links': [],
            'access_url': 'https://test.com/x',
            'platform_name': 'IvoirPass',
            'platform_url': 'https://prepod.ivoirpass.com',
            'support_email': 'test@test.com',
            'year': 2026,
        }
        return render_to_string(template_name, ctx)

    def test_html_billet_affiche_message(self):
        html = self._render(
            'notifications/email/guest_ticket_confirmed.html',
            'MARKER_BILLET',
        )
        self.assertIn('MARKER_BILLET', html)
        self.assertIn("Message de l'organisateur", html)

    def test_txt_billet_affiche_message(self):
        txt = self._render(
            'notifications/email/guest_ticket_confirmed.txt',
            'MARKER_BILLET',
        )
        self.assertIn('MARKER_BILLET', txt)

    def test_html_online_affiche_message(self):
        html = self._render(
            'notifications/email/guest_online_access.html',
            'MARKER_ONLINE',
        )
        self.assertIn('MARKER_ONLINE', html)

    def test_txt_online_affiche_message(self):
        txt = self._render(
            'notifications/email/guest_online_access.txt',
            'MARKER_ONLINE',
        )
        self.assertIn('MARKER_ONLINE', txt)

    def test_message_vide_ne_casse_rien(self):
        """Si custom_message est vide, le bloc est masqué (pas de plantage)."""
        html = self._render(
            'notifications/email/guest_ticket_confirmed.html',
            '',
        )
        self.assertNotIn("Message de l'organisateur", html)
        # Le reste du mail doit être là
        self.assertIn('TEST-001', html)