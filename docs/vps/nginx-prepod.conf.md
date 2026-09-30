# Configuration nginx preprod (prepod.ivoirpass.com)

## Directive importante
- `client_max_body_size 110M;` dans le bloc `server` HTTPS
  → permet l'upload des vidéos mp4 jusqu'à 100 Mo
  → NE PAS remettre à 20M (défaut) : erreur 413 à l'upload vidéo

## Fichier concerné
- VPS : `/etc/nginx/sites-enabled/prepod-ivoirpass`
- Rechargement : `sudo systemctl reload nginx`
