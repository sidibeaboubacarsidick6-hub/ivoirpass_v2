"""
Tests unitaires du chatbot IvoirPass.

Couvre :
- Chargement des docs
- Recherche dans l'index mots-clés
- Endpoint API (validation, rate limit, feature flag)
- Compteur d'échecs → suggestion WhatsApp
"""
import json
from unittest.mock import patch, MagicMock

from django.core.cache import cache
from django.test import TestCase, Client, override_settings


class ChatbotServiceDocsTests(TestCase):
    """Tests du chargement des documents."""

    def test_load_docs(self):
        from apps.chatbot.service import ChatbotService
        ChatbotService._docs_cache = None
        docs = ChatbotService._load_docs()
        self.assertIn('guide-utilisateur', docs)
        self.assertIn('cgu', docs)
        self.assertGreater(len(docs['guide-utilisateur']), 10)
        self.assertGreater(len(docs['cgu']), 10)

    def test_load_index(self):
        from apps.chatbot.service import ChatbotService
        ChatbotService._index_cache = None
        index = ChatbotService._load_index()
        self.assertGreater(len(index), 100)
        self.assertIn('wave', index)

    def test_find_relevant_sections(self):
        from apps.chatbot.service import ChatbotService
        ChatbotService._docs_cache = None
        ChatbotService._index_cache = None
        sections = ChatbotService.find_relevant_sections('comment acheter un billet')
        self.assertGreater(len(sections), 0)
        self.assertIn('Achat', sections[0]['title'])


@override_settings(
    CHATBOT_ENABLED=True,
    MISTRAL_API_KEY='test_key',
    CHATBOT_WHATSAPP_NUMBER='2250000000000',
    CHATBOT_RATE_LIMIT_PER_HOUR=100,  # éviter le rate limit dans les tests
)
class ChatbotAPITests(TestCase):
    """Tests de l'endpoint /api/chat/message/."""

    def setUp(self):
        cache.clear()  # reset les sessions
        self.client = Client()

    # ------------------------------------------------------------------
    # Validation entrée
    # ------------------------------------------------------------------
    def test_message_vide_rejete(self):
        r = self.client.post(
            '/api/chat/message/',
            data=json.dumps({'message': '', 'session_key': 'abc'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_session_key_manquante_rejete(self):
        r = self.client.post(
            '/api/chat/message/',
            data=json.dumps({'message': 'Bonjour'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_message_trop_long_rejete(self):
        r = self.client.post(
            '/api/chat/message/',
            data=json.dumps({'message': 'x' * 501, 'session_key': 'abc'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_json_invalide_rejete(self):
        r = self.client.post(
            '/api/chat/message/',
            data='not json',
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------
    # Réponse OK
    # ------------------------------------------------------------------
    @patch('apps.chatbot.service.requests.post')
    def test_reponse_ok(self, mock_post):
        """Test nominal : question simple → réponse de Mistral."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'Pour acheter un billet, cliquez...'}}]
        }
        mock_post.return_value = mock_response

        r = self.client.post(
            '/api/chat/message/',
            data=json.dumps({
                'message': 'Comment acheter un billet ?',
                'session_key': 'session-test-1',
            }),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('Pour acheter', data['answer'])
        self.assertFalse(data['suggest_whatsapp'])
        self.assertIn('whatsapp_url', data)

    @patch('apps.chatbot.service.requests.post')
    def test_mistral_echec_fallback(self, mock_post):
        """Si Mistral échoue, on renvoie le message WhatsApp."""
        mock_post.side_effect = Exception('Timeout')

        r = self.client.post(
            '/api/chat/message/',
            data=json.dumps({
                'message': 'Comment acheter un billet ?',
                'session_key': 'session-test-2',
            }),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('WhatsApp', data['answer'])

    # ------------------------------------------------------------------
    # Compteur d'échecs
    # ------------------------------------------------------------------
    @patch('apps.chatbot.service.requests.post')
    def test_2_echecs_suggest_whatsapp(self, mock_post):
        """2 échecs consécutifs → suggest_whatsapp=True."""
        # Simuler un échec : aucune section ne matche + Mistral échoue
        mock_post.side_effect = Exception('Timeout')

        for i in range(2):
            r = self.client.post(
                '/api/chat/message/',
                data=json.dumps({
                    'message': 'xyzabcquestionbidon',
                    'session_key': 'session-echecs',
                }),
                content_type='application/json',
            )
            self.assertEqual(r.status_code, 200)

        # 2e appel → suggest_whatsapp doit être True
        data = r.json()
        self.assertTrue(data['suggest_whatsapp'])

    # ------------------------------------------------------------------
    # Limite par session
    # ------------------------------------------------------------------
    @override_settings(CHATBOT_MAX_MESSAGES_PER_SESSION=2)
    @patch('apps.chatbot.service.requests.post')
    def test_limite_session(self, mock_post):
        """Après N messages, on suggère WhatsApp."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'OK'}}]
        }
        mock_post.return_value = mock_response

        for i in range(3):
            r = self.client.post(
                '/api/chat/message/',
                data=json.dumps({
                    'message': f'Question {i}',
                    'session_key': 'session-limite',
                }),
                content_type='application/json',
            )
        data = r.json()
        self.assertTrue(data['suggest_whatsapp'])


@override_settings(CHATBOT_ENABLED=False)
class ChatbotDisabledTests(TestCase):
    """Test du feature flag."""

    def test_chatbot_desactive_renvoie_503(self):
        c = Client()
        r = c.post(
            '/api/chat/message/',
            data=json.dumps({'message': 'Bonjour', 'session_key': 'abc'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 503)
