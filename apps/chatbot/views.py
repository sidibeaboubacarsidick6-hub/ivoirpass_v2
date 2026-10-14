"""
IvoirPass V2 — Vues de l'app chatbot.
"""
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.core import is_ratelimited

from .service import ChatbotService

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def chat_message(request):
    """
    Endpoint du chatbot.

    Body JSON :
        {"message": "question du client", "session_key": "uuid-abc"}

    Réponse JSON :
        {
            "answer": "...",
            "suggest_whatsapp": bool,
            "whatsapp_url": "..."
        }

    Rate limiting :
        CHATBOT_RATE_LIMIT_PER_HOUR messages par heure et par IP.
        Renvoie un JSON propre avec status 429 si la limite est atteinte
        (au lieu du 403 HTML par défaut de django_ratelimit).
    """
    # ── Rate limiting manuel → message JSON clair ─────────────────
    rate_limit = getattr(settings, 'CHATBOT_RATE_LIMIT_PER_HOUR', 30)
    if is_ratelimited(
        request=request,
        group='chatbot:chat_message',
        key='ip',
        rate=f"{rate_limit}/h",
        method='POST',
        increment=True,
    ):
        return JsonResponse(
            {
                'error': (
                    "Vous avez envoyé beaucoup de messages récemment. "
                    "Patientez quelques minutes ou contactez notre support WhatsApp."
                ),
            },
            status=429,
        )

    # ── Feature flag ──────────────────────────────────────────────
    if not getattr(settings, 'CHATBOT_ENABLED', False):
        return JsonResponse(
            {'error': 'Chatbot désactivé.'},
            status=503,
        )

    # ── Parse du body ─────────────────────────────────────────────
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON invalide.'}, status=400)

    message = (body.get('message') or '').strip()
    session_key = (body.get('session_key') or '').strip()

    # ── Validation ────────────────────────────────────────────────
    if not message:
        return JsonResponse({'error': 'Message vide.'}, status=400)
    if len(message) > 500:
        return JsonResponse(
            {'error': 'Message trop long (500 caractères max).'},
            status=400,
        )
    if not session_key or len(session_key) > 100:
        return JsonResponse(
            {'error': 'session_key manquante ou invalide.'},
            status=400,
        )

    # ── Appel du service RAG ──────────────────────────────────────
    try:
        result = ChatbotService.answer(message, session_key)
    except Exception as e:
        logger.exception("Chatbot erreur : %s", e)
        return JsonResponse(
            {'error': 'Erreur interne. Veuillez réessayer.'},
            status=500,
        )

    return JsonResponse({
        'answer': result['answer'],
        'suggest_whatsapp': result['suggest_whatsapp'],
        'whatsapp_url': ChatbotService.build_whatsapp_url(),
    })