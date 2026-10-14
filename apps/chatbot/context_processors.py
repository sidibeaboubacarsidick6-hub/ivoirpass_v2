"""
IvoirPass V2 — Context processor du chatbot.

Expose `CHATBOT_ENABLED` aux templates, pour n'inclure le widget
que lorsque le flag est actif dans .env.

Les settings Django ne sont pas accessibles directement dans les
templates — ce context processor les y injecte explicitement.
"""
from django.conf import settings


def chatbot(request):
    """Ajoute CHATBOT_ENABLED + numéro WhatsApp à tous les templates."""
    return {
        'CHATBOT_ENABLED': getattr(settings, 'CHATBOT_ENABLED', False),
        'CHATBOT_WHATSAPP_NUMBER': getattr(
            settings, 'CHATBOT_WHATSAPP_NUMBER', '2250702063876',
        ),
    }
