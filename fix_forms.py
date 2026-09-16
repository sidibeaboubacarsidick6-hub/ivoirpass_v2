import os

forms_file = 'apps/events/forms.py'

with open(forms_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacement exact
old_code = '''        if event_type in (
            Event.EventType.ONLINE,
            Event.EventType.HYBRID,
        ) and not online_link:
            self.add_error(
                'online_link',
                "Le lien en ligne est obligatoire pour un événement en ligne ou hybride."
            )'''

new_code = '''        if event_type == Event.EventType.ONLINE and not online_link:
            self.add_error(
                'online_link',
                "Le lien en ligne est obligatoire pour un événement en ligne."
            )'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(forms_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✅ forms.py modifié avec succès !")
else:
    print("❌ Code non trouvé. Vérifie le fichier.")
