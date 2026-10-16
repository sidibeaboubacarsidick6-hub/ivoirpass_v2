"""
IvoirPass V2 — Service Chatbot IA.

Moteur RAG simple : recherche par mots-clés dans les documents
(guide-utilisateur.md + cgu.md), puis envoie la question + le contexte
à Mistral pour formuler une réponse en français.

⚠️ Feature-flagged : le widget n'est affiché que si CHATBOT_ENABLED=True.
"""
import json
import logging
import re
import unicodedata
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────
# CONSTANTES
# ───────────────────────────────────────────────────────────
DOCS_DIR = Path(settings.BASE_DIR) / 'docs' / 'chatbot'

WHATSAPP_FALLBACK_MESSAGE = (
    "Je n'ai pas cette information dans ma documentation. "
    "Contactez notre support sur WhatsApp au +225 07 02 06 38 76 "
    "pour une réponse personnalisée."
)

SYSTEM_PROMPT = """Tu es l'assistant virtuel d'IvoirPass, une plateforme ivoirienne de billetterie et de distribution culturelle.

RÈGLES ABSOLUES :
1. Réponds UNIQUEMENT avec les informations du CONTEXTE fourni ci-dessous.
2. Si l'information n'est PAS dans le contexte, réponds exactement :
   "Je n'ai pas cette information. Contactez notre support sur WhatsApp au +225 07 02 06 38 76."
3. Ne promets JAMAIS un remboursement, une annulation, un geste commercial ou une action quelconque. Pour ce type de demande, redirige vers WhatsApp.
4. Ne réponds jamais en anglais — uniquement en français.
5. Sois concis, courtois et professionnel. Maximum 4 phrases par réponse.
6. Ne mentionne PAS que tu as reçu un "contexte" ou que tu cites des documents — réponds comme si c'était ta connaissance.
7. Si la question est hors sujet (météo, actualité, etc.), dis poliment que tu ne réponds qu'aux questions sur IvoirPass.

Ton ton est chaleureux mais professionnel."""


# ───────────────────────────────────────────────────────────
# UTILITAIRES TEXTE
# ───────────────────────────────────────────────────────────
def _slugify_anchor(title):
    """Reproduit les ancres GitHub markdown."""
    s = title.lower()
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def _normalize_text(text):
    """Minuscule + suppression accents."""
    s = text.lower()
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s


def _stem(word):
    """Radicalisation légère pour matcher les variantes françaises."""
    suffixes = [
        'ements', 'ement', 'ations', 'ation', 'isses', 'isse',
        'er', 'es', 'ee', 'ez', 'e',
        's', 'x',
    ]
    for suf in suffixes:
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[:-len(suf)]
    return word


def _get_stemmed_words(text):
    """Retourne l'ensemble des radicaux des mots >= 3 lettres."""
    normalized = _normalize_text(text)
    words = re.findall(r'\w{3,}', normalized)
    return {_stem(w) for w in words}


# ───────────────────────────────────────────────────────────
# SERVICE
# ───────────────────────────────────────────────────────────
class ChatbotService:
    """Service principal du chatbot."""

    _docs_cache = None
    _index_cache = None

    # ------------------------------------------------------------------
    # CHARGEMENT DES DOCS
    # ------------------------------------------------------------------
    @classmethod
    def _load_docs(cls):
        """Charge les 2 fichiers markdown en sections."""
        if cls._docs_cache is not None:
            return cls._docs_cache

        docs = {}
        for filename, key in [
            ('guide-utilisateur.md', 'guide-utilisateur'),
            ('cgu.md', 'cgu'),
        ]:
            path = DOCS_DIR / filename
            if not path.exists():
                logger.warning("Chatbot : fichier manquant %s", path)
                docs[key] = {}
                continue

            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            sections = {}
            parts = re.split(r'\n## ', content)
            for part in parts[1:]:
                lines = part.split('\n', 1)
                title = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ''
                sections[_slugify_anchor(title)] = {
                    'title': title,
                    'content': body,
                }
            docs[key] = sections

        cls._docs_cache = docs
        return docs

    @classmethod
    def _load_index(cls):
        """Charge l'index mots-clés → sections."""
        if cls._index_cache is not None:
            return cls._index_cache

        path = DOCS_DIR / 'index-mots-cles.json'
        with open(path, 'r', encoding='utf-8') as f:
            cls._index_cache = json.load(f)
        return cls._index_cache

    # ------------------------------------------------------------------
    # RECHERCHE
    # ------------------------------------------------------------------
    @classmethod
    def find_relevant_sections(cls, question, top_n=3):
        """Trouve les sections pertinentes via l'index mots-clés."""
        index = cls._load_index()
        docs = cls._load_docs()

        q_words = _get_stemmed_words(question)
        q_norm = _normalize_text(question)

        scores = {}
        for keyword, section_ref in index.items():
            kw_words = _get_stemmed_words(keyword)
            if not kw_words:
                continue
            common = q_words & kw_words
            if common:
                score = len(common) / len(kw_words)
                if _normalize_text(keyword) in q_norm:
                    score += 1.0
                scores[keyword] = (score, section_ref)

        sorted_results = sorted(scores.items(), key=lambda x: -x[1][0])

        seen_anchors = set()
        results = []
        for keyword, (score, ref) in sorted_results:
            if ref in seen_anchors:
                continue
            seen_anchors.add(ref)
            file_part, _, anchor = ref.partition('#')
            if not anchor:
                continue
            file_key = file_part.replace('.md', '')
            section = docs.get(file_key, {}).get(anchor)
            if section:
                results.append({
                    'keyword': keyword,
                    'score': score,
                    'source': file_part,
                    'title': section['title'],
                    'content': section['content'],
                })
            if len(results) >= top_n:
                break
        return results

    # ------------------------------------------------------------------
    # APPEL MISTRAL
    # ------------------------------------------------------------------
    @classmethod
    def _ask_mistral(cls, question, context_sections, history):
        """Envoie la question + contexte à Mistral."""
        api_key = getattr(settings, 'MISTRAL_API_KEY', '')
        if not api_key:
            logger.error("Chatbot : MISTRAL_API_KEY non définie")
            return None

        if context_sections:
            context_text = "\n\n".join(
                f"### {s['title']}\n{s['content']}"
                for s in context_sections
            )
        else:
            context_text = "(Aucune section pertinente trouvée)"

        user_message = f"""CONTEXTE :
{context_text}

QUESTION DU CLIENT :
{question}"""

        messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({'role': 'user', 'content': user_message})

        payload = {
            'model': getattr(settings, 'MISTRAL_MODEL', 'open-mistral-7b'),
            'messages': messages,
            'temperature': 0.2,
            'max_tokens': 400,
        }

        try:
            r = requests.post(
                getattr(settings, 'MISTRAL_API_URL', 'https://api.mistral.ai/v1/chat/completions'),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'User-Agent': 'IvoirPass/1.0 (+https://ivoirpass.com)',
                },
                json=payload,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            return data['choices'][0]['message']['content'].strip()
        except requests.HTTPError as e:
            logger.error("Chatbot Mistral HTTP %s : %s", r.status_code, r.text[:200])
            return None
        except Exception as e:
            logger.exception("Chatbot Mistral erreur : %s", e)
            return None

    # ------------------------------------------------------------------
    # SESSION (cache Redis)
    # ------------------------------------------------------------------
    @staticmethod
    def _session_key(session_key):
        return f'chatbot:session:{session_key}'

    @classmethod
    def get_session(cls, session_key):
        """Récupère ou crée la session."""
        key = cls._session_key(session_key)
        data = cache.get(key)
        if data is None:
            data = {'history': [], 'failures': 0, 'count': 0}
        return data

    @classmethod
    def save_session(cls, session_key, data):
        """Sauvegarde la session avec TTL."""
        key = cls._session_key(session_key)
        ttl = getattr(settings, 'CHATBOT_HISTORY_TTL_SECONDS', 900)
        cache.set(key, data, timeout=ttl)

    @classmethod
    def reset_session(cls, session_key):
        """Réinitialise la session (utilisé si max messages atteint)."""
        key = cls._session_key(session_key)
        cache.delete(key)

    # ------------------------------------------------------------------
    # API PUBLIQUE
    # ------------------------------------------------------------------
    @classmethod
    def answer(cls, question, session_key):
        """
        Wrapper public : calcule la réponse puis log l'interaction en DB.
        """
        result = cls._answer_impl(question, session_key)
        cls._log_interaction(question, session_key, result)
        return result

    @classmethod
    def _answer_impl(cls, question, session_key):
        """
        Répond à une question (implémentation — pas de log DB ici).

        Returns:
            dict {
                'answer': str,
                'suggest_whatsapp': bool,
                'sections_found': int,
                'error': str | None,
            }
        """
        # 1. Vérifier la config
        if not getattr(settings, 'CHATBOT_ENABLED', False):
            return {
                'answer': "L'assistant est temporairement indisponible.",
                'suggest_whatsapp': True,
                'sections_found': 0,
                'error': 'disabled',
            }

        # 2. Récupérer la session
        session = cls.get_session(session_key)

        # 3. Vérifier la limite par session
        max_msgs = getattr(settings, 'CHATBOT_MAX_MESSAGES_PER_SESSION', 30)
        if session['count'] >= max_msgs:
            return {
                'answer': (
                    "Vous avez atteint le nombre maximum de messages pour cette "
                    "conversation. Pour continuer, contactez notre support WhatsApp."
                ),
                'suggest_whatsapp': True,
                'sections_found': 0,
                'error': 'session_limit',
            }

        # 4. Rechercher les sections pertinentes
        sections = cls.find_relevant_sections(question)

        # 5. Déterminer si c'est un échec (aucune section trouvée)
        is_failure = (len(sections) == 0)
        if is_failure:
            session['failures'] += 1

        # 6. Appeler Mistral
        answer_text = cls._ask_mistral(
            question, sections, session['history'],
        )

        # 7. Fallback si Mistral a échoué
        if answer_text is None:
            answer_text = WHATSAPP_FALLBACK_MESSAGE
            session['failures'] += 1

        # 8. Mettre à jour l'historique
        session['history'].append({'role': 'user', 'content': question})
        session['history'].append({'role': 'assistant', 'content': answer_text})
        # Limiter à 3 échanges (6 messages)
        session['history'] = session['history'][-6:]
        session['count'] += 1

        # 9. Suggestion WhatsApp après N échecs
        failures_threshold = getattr(settings, 'CHATBOT_FAILURES_BEFORE_WHATSAPP', 2)
        suggest_whatsapp = (session['failures'] >= failures_threshold)

        # 10. Sauvegarder la session
        cls.save_session(session_key, session)

        # 11. Log si échec (utile pour améliorer l'index)
        if is_failure or answer_text == WHATSAPP_FALLBACK_MESSAGE:
            logger.info(
                "Chatbot échec — session=%s question=%r sections=%d",
                session_key[:8], question[:100], len(sections),
            )

        return {
            'answer': answer_text,
            'suggest_whatsapp': suggest_whatsapp,
            'sections_found': len(sections),
            'error': None,
        }
    @classmethod
    def _log_interaction(cls, question, session_key, result):
        """
        Enregistre l'interaction en DB (ChatbotLog).
        Silencieux si erreur — ne doit jamais casser le chat.
        """
        try:
            from .models import ChatbotLog

            # Déterminer was_failure + error_type
            error_type = result.get('error') or ''
            sections_found = result.get('sections_found', 0)

            if not error_type:
                if sections_found == 0:
                    error_type = ChatbotLog.ErrorType.NO_SECTIONS
                elif result.get('answer', '').strip().startswith("Je n'ai pas cette information"):
                    error_type = ChatbotLog.ErrorType.MISTRAL_FAILED

            was_failure = bool(error_type)

            ChatbotLog.objects.create(
                question=question[:5000],
                answer=(result.get('answer') or '')[:5000],
                session_key=(session_key or '')[:100],
                sections_found=sections_found,
                was_failure=was_failure,
                error_type=error_type if error_type in dict(ChatbotLog.ErrorType.choices) else '',
            )
        except Exception as e:
            logger.warning(f"ChatbotLog création échouée : {e}")
            
    @classmethod
    def build_whatsapp_url(cls):
        """Construit l'URL WhatsApp avec le message pré-rempli."""
        number = getattr(settings, 'CHATBOT_WHATSAPP_NUMBER', '2250702063876')
        message = (
            "Bonjour, je contacte le support technique IvoirPass.\n\n"
            "Voici mon problème :\n"
            "[Décrivez ici votre problème complet avec toutes les informations utiles : "
            "numéro de commande, email, date, motif]\n\n"
            "Merci."
        )
        from urllib.parse import quote
        return f"https://wa.me/{number}?text={quote(message)}"
