"""
POC Chatbot IvoirPass — Moteur RAG simple.

Usage :
    python poc_chatbot/chat.py

Pose une question, récupère une réponse basée sur les docs
(guide-utilisateur.md + cgu.md).

Le script garde le contexte de la conversation (limité à 3 échanges)
et détecte quand il ne peut pas répondre pour suggérer WhatsApp.
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import requests
from dotenv import load_dotenv

# ───────────────────────────────────────────────────────────
# CONFIGURATION
# ───────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT.parent / 'docs' / 'chatbot'

load_dotenv(ROOT / '.env')

API_KEY = os.getenv('MISTRAL_API_KEY')
API_URL = os.getenv('MISTRAL_API_URL', 'https://api.mistral.ai/v1/chat/completions')
MODEL = os.getenv('MISTRAL_MODEL', 'open-mistral-7b')

WHATSAPP_NUMBER = '2250702063876'
MAX_HISTORY = 3  # nombre d'échanges gardés en mémoire


# ───────────────────────────────────────────────────────────
# CHARGEMENT DES DOCS
# ───────────────────────────────────────────────────────────
def load_doc(filename):
    """Charge un fichier markdown et le découpe en sections par '##'."""
    path = DOCS_DIR / filename
    if not path.exists():
        print(f"⚠️ Fichier manquant : {path}")
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    sections = {}
    # Découpe sur les titres '## ' (niveau 2)
    # Format attendu : "## Titre de la section\n...contenu...\n## Section suivante"
    parts = re.split(r'\n## ', content)

    # Le premier "parts[0]" contient le titre principal + intro, on l'ignore
    for part in parts[1:]:
        lines = part.split('\n', 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ''
        # Clé = ancre slugifiée pour matcher avec index-mots-cles.json
        anchor = slugify_anchor(title)
        sections[anchor] = {'title': title, 'content': body}
    return sections


def slugify_anchor(title):
    """
    Reproduit la logique des ancres markdown GitHub :
    'Article 1 — Éditeur de la plateforme' → 'article-1--editeur-de-la-plateforme'
    """
    # Minuscule + suppression accents
    s = title.lower()
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    # Remplace tout ce qui n'est pas a-z0-9 par des tirets
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s


def load_index():
    """Charge l'index mots-clés → section."""
    path = DOCS_DIR / 'index-mots-cles.json'
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ───────────────────────────────────────────────────────────
# RECHERCHE
# ───────────────────────────────────────────────────────────
def _stem(word):
    """
    Radicalisation légère pour matcher les variantes françaises.
    Ex: 'rembourser' → 'rembours', 'remboursement' → 'rembours'
    """
    # Suffixes français courants, du plus long au plus court
    suffixes = [
        'ements', 'ement', 'ations', 'ation', 'isses', 'isse',
        'er', 'es', 'ee', 'ez', 'ee', 'e',
        's', 'x',
    ]
    for suf in suffixes:
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[:-len(suf)]
    return word


def normalize_text(text):
    """Minuscule + suppression accents + racines communes."""
    s = text.lower()
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    return s


def get_stemmed_words(text):
    """Retourne l'ensemble des radicaux des mots >= 3 lettres."""
    normalized = normalize_text(text)
    words = re.findall(r'\w{3,}', normalized)
    return {_stem(w) for w in words}


def find_relevant_sections(question, index, docs, top_n=3):
    """
    Cherche les sections pertinentes en matchant la question avec les
    mots-clés de l'index. Score = nombre de mots-clés qui matchent.
    """
    q_norm = normalize_text(question)
    # Découpe la question en mots pour matching plus fin
    q_words = get_stemmed_words(question)

    scores = {}  # clé index → score
    for keyword, section_ref in index.items():
        kw_norm = normalize_text(keyword)
        # Score : match exact de la phrase OU chaque mot du mot-clé présent
        kw_words = get_stemmed_words(keyword)
        if not kw_words:
            continue
        common = q_words & kw_words
        if common:
            score = len(common) / len(kw_words)  # ratio de recouvrement
            # Bonus si la phrase entière matche
            if kw_norm in q_norm:
                score += 1.0
            scores[keyword] = (score, section_ref)

    # Trier par score décroissant
    sorted_results = sorted(scores.items(), key=lambda x: -x[1][0])

    # Extraire les sections uniques (dédupliquer)
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


# ───────────────────────────────────────────────────────────
# MISTRAL
# ───────────────────────────────────────────────────────────
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


def ask_mistral(question, context_sections, history):
    """Envoie la question + contexte à Mistral et retourne la réponse."""
    if context_sections:
        context_text = "\n\n".join(
            f"### {s['title']}\n{s['content']}"
            for s in context_sections
        )
    else:
        context_text = "(Aucune section pertinente trouvée dans la documentation)"

    user_message = f"""CONTEXTE :
{context_text}

QUESTION DU CLIENT :
{question}"""

    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({'role': 'user', 'content': user_message})

    payload = {
        'model': MODEL,
        'messages': messages,
        'temperature': 0.2,
        'max_tokens': 400,
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
        return data['choices'][0]['message']['content'].strip()
    except requests.HTTPError as e:
        return f"⚠️ Erreur technique : {r.status_code} — {r.text[:200]}"
    except Exception as e:
        return f"⚠️ Erreur : {e}"


# ───────────────────────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────────────────────
def main():
    if not API_KEY or API_KEY.startswith('colle'):
        print('❌ MISTRAL_API_KEY non définie dans poc_chatbot/.env')
        sys.exit(1)

    print("═" * 60)
    print("  Chatbot IvoirPass — POC local")
    print(f"  Modèle : {MODEL}")
    print("  Tape 'quit' pour quitter")
    print("═" * 60)
    print()

    # Charger les docs
    docs = {
        'guide-utilisateur': load_doc('guide-utilisateur.md'),
        'cgu': load_doc('cgu.md'),
    }
    total_sections = sum(len(d) for d in docs.values())
    print(f"→ {total_sections} sections chargées depuis les docs")
    print(f"→ {len(load_index())} mots-clés dans l'index")
    print()

    history = []  # liste de {role, content}

    while True:
        try:
            question = input("Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue
        if question.lower() in ('quit', 'exit', 'q'):
            break

        # Recherche
        index = load_index()
        sections = find_relevant_sections(question, index, docs)

        if sections:
            print(f"\n[debug] {len(sections)} section(s) trouvée(s) :")
            for s in sections:
                print(f"  · {s['source']} → {s['title']} (score {s['score']:.2f})")

        # Appel Mistral
        answer = ask_mistral(question, sections, history)
        print(f"\nAssistant : {answer}\n")

        # Mise à jour de l'historique
        history.append({'role': 'user', 'content': question})
        history.append({'role': 'assistant', 'content': answer})
        # Limiter à MAX_HISTORY échanges (2 messages par échange)
        history = history[-(MAX_HISTORY * 2):]


if __name__ == '__main__':
    main()
