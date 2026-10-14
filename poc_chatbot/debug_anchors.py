"""
Diagnostic : liste les sections des .md avec leurs ancres générées,
et croise avec les références de l'index pour voir ce qui matche (et
ce qui ne matche PAS).
"""
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT.parent / 'docs' / 'chatbot'


def slugify_anchor(title):
    s = title.lower()
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s


def load_doc_sections(filename):
    path = DOCS_DIR / filename
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    sections = {}
    parts = re.split(r'\n## ', content)
    for part in parts[1:]:
        lines = part.split('\n', 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ''
        anchor = slugify_anchor(title)
        sections[anchor] = {'title': title, 'content_len': len(body)}
    return sections


# Charger les sections
guide = load_doc_sections('guide-utilisateur.md')
cgu = load_doc_sections('cgu.md')

print("═" * 70)
print("ANCRES GÉNÉRÉES pour guide-utilisateur.md :")
print("═" * 70)
for anchor, sec in guide.items():
    print(f"  {anchor}")
    print(f"    → {sec['title']}")

print()
print("═" * 70)
print("ANCRES GÉNÉRÉES pour cgu.md :")
print("═" * 70)
for anchor, sec in cgu.items():
    print(f"  {anchor}")
    print(f"    → {sec['title']}")

print()
print("═" * 70)
print("RÉFÉRENCES DE L'INDEX → MATCH ?")
print("═" * 70)

with open(DOCS_DIR / 'index-mots-cles.json', 'r', encoding='utf-8') as f:
    index = json.load(f)

files = {'guide-utilisateur': guide, 'cgu': cgu}
missing = []
matched = 0
for keyword, ref in index.items():
    file_part, _, anchor = ref.partition('#')
    if not anchor:
        missing.append((keyword, ref, "PAS D'ANCRE"))
        continue
    file_key = file_part.replace('.md', '')
    target = files.get(file_key, {}).get(anchor)
    if target:
        matched += 1
    else:
        missing.append((keyword, ref, "ANCRE INTROUVABLE"))

print(f"✅ {matched} références valides")
print(f"❌ {len(missing)} références invalides :")
print()
for keyword, ref, reason in missing:
    print(f"  · '{keyword}' → {ref}")
    print(f"    RAISON : {reason}")
