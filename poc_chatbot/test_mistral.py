"""
Test simple : valider que la clé Mistral fonctionne.
Envoie une question basique et affiche la réponse.
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Charger le .env
load_dotenv(Path(__file__).parent / '.env')

API_KEY = os.getenv('MISTRAL_API_KEY')
API_URL = os.getenv('MISTRAL_API_URL')
MODEL = os.getenv('MISTRAL_MODEL')

if not API_KEY or API_KEY.startswith('colle'):
    print('❌ MISTRAL_API_KEY non définie dans poc_chatbot/.env')
    sys.exit(1)

print(f'→ Test connexion à Mistral (modèle : {MODEL})')
print(f'→ Clé utilisée : {API_KEY[:6]}... (masquée)')
print()

payload = {
    'model': MODEL,
    'messages': [
        {'role': 'system', 'content': 'Tu es un assistant. Réponds en français.'},
        {'role': 'user', 'content': 'Dis juste "Bonjour IvoirPass, je fonctionne !" sans rien ajouter.'},
    ],
    'temperature': 0.0,
    'max_tokens': 50,
}

try:
    r = requests.post(
        API_URL,
        headers={
            'Authorization': f'Bearer {API_KEY}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    answer = data['choices'][0]['message']['content']
    print('✅ Connexion OK')
    print()
    print('Réponse de Mistral :')
    print(answer)
    print()
    print(f'Tokens utilisés : {data["usage"]["total_tokens"]}')
except requests.HTTPError as e:
    print(f'❌ Erreur HTTP : {r.status_code}')
    print(r.text[:500])
except Exception as e:
    print(f'❌ Erreur : {e}')
