"""
Tests Vague 2 — Upload vidéo événement (2026-09-30).

Vérifie :
- La propriété Event.video_embed_url (conversion YouTube/Vimeo, priorité
  fichier uploadé, fallback URL brute, None si rien).
- Les validateurs du champ video_file (extension mp4, taille max 100 Mo).
"""
import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.events.models import Event


# ============================================
# Helpers
# ============================================
def _make_video_file(name='test.mp4', size_bytes=1024):
    """Crée un fichier vidéo factice de la taille voulue."""
    content = b'\x00' * size_bytes
    return SimpleUploadedFile(name, content, content_type='video/mp4')


# ============================================
# Tests video_embed_url
# ============================================
class VideoEmbedUrlTests(TestCase):
    """Vérifie la propriété video_embed_url."""

    def test_aucune_video_retourne_none(self):
        event = Event(video_url='')
        self.assertIsNone(event.video_embed_url)

    def test_video_url_vide_retourne_none(self):
        event = Event(video_url='   ')
        self.assertIsNone(event.video_embed_url)

    def test_youtube_watch_converti_en_embed(self):
        event = Event(video_url='https://www.youtube.com/watch?v=ABC123xyz')
        self.assertEqual(
            event.video_embed_url,
            'https://www.youtube.com/embed/ABC123xyz',
        )

    def test_youtube_short_converti_en_embed(self):
        event = Event(video_url='https://youtu.be/ABC123xyz')
        self.assertEqual(
            event.video_embed_url,
            'https://www.youtube.com/embed/ABC123xyz',
        )

    def test_youtube_shorts_converti_en_embed(self):
        event = Event(video_url='https://youtube.com/shorts/ABC123xyz')
        self.assertEqual(
            event.video_embed_url,
            'https://www.youtube.com/embed/ABC123xyz',
        )

    def test_vimeo_converti_en_player(self):
        event = Event(video_url='https://vimeo.com/123456789')
        self.assertEqual(
            event.video_embed_url,
            'https://player.vimeo.com/video/123456789',
        )

    def test_vimeo_video_prefix_converti(self):
        event = Event(video_url='https://vimeo.com/video/123456789')
        self.assertEqual(
            event.video_embed_url,
            'https://player.vimeo.com/video/123456789',
        )

    def test_autre_url_retournee_telle_quelle(self):
        event = Event(video_url='https://example.com/vid')
        self.assertEqual(event.video_embed_url, 'https://example.com/vid')

    @patch('apps.events.models.Event.video_file')
    def test_video_file_prioritaire_sur_url(self, mock_file):
        """Le fichier uploadé gagne sur le lien externe."""
        mock_file.__bool__ = lambda self: True
        type(mock_file).url = property(
            lambda self: '/media/events/videos/2026/09/clip.mp4'
        )

        event = Event(video_url='https://www.youtube.com/watch?v=ABC123xyz')
        event.video_file = mock_file

        self.assertEqual(
            event.video_embed_url,
            '/media/events/videos/2026/09/clip.mp4',
        )


# ============================================
# Tests validateurs video_file
# ============================================
class VideoFileValidatorTests(TestCase):
    """Vérifie les validateurs du champ video_file."""

    def test_extension_mp4_acceptee(self):
        event = Event()
        f = _make_video_file('clip.mp4')
        # Ne doit pas lever
        event.video_file = f
        # Pas d'appel à full_clean → on valide directement le champ
        field = Event._meta.get_field('video_file')
        field.run_validators(f)

    def test_extension_mov_rejetee(self):
        event = Event()
        f = _make_video_file('clip.mov')
        field = Event._meta.get_field('video_file')
        with self.assertRaises(ValidationError):
            field.run_validators(f)

    def test_extension_avi_rejetee(self):
        event = Event()
        f = _make_video_file('clip.avi')
        field = Event._meta.get_field('video_file')
        with self.assertRaises(ValidationError):
            field.run_validators(f)

    def test_fichier_trop_gros_rejete(self):
        """101 Mo doit être rejeté (limite 100 Mo)."""
        event = Event()
        f = _make_video_file('clip.mp4', size_bytes=101 * 1024 * 1024)
        field = Event._meta.get_field('video_file')
        with self.assertRaises(ValidationError):
            field.run_validators(f)

    def test_fichier_99_mo_accepte(self):
        """99 Mo doit passer."""
        event = Event()
        f = _make_video_file('clip.mp4', size_bytes=99 * 1024 * 1024)
        field = Event._meta.get_field('video_file')
        # Ne doit pas lever
        field.run_validators(f)