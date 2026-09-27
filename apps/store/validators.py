"""
IvoirPass V2 — Validateurs d'upload boutique.

Sécurité : chaque type de fichier a une liste blanche d'extensions
et une taille maximale en Mo. Ces validateurs s'appliquent au niveau
du formulaire — aucune contrainte SQL n'est créée en base, donc la
migration associée est purement déclarative (state-only).

NOTE SÉRIALISATION MIGRATION :
`FileSizeValidator` est décoré `@deconstructible` — indispensable pour
que Django puisse le sérialiser dans les migrations (un closure retourné
par une factory ne serait pas importable par nom → ValueError à
`makemigrations`). La factory `validate_file_size(max_mb)` reste
disponible pour l'API publique, elle retourne simplement une instance
sérialisable.
"""
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


# ── Extensions autorisées par type ──────────────────────────────────
EXTENSIONS = {
    'audio':   ['.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg'],
    'video':   ['.mp4', '.mov', '.webm'],
    'book':    ['.pdf', '.epub'],
    'image':   ['.jpg', '.jpeg', '.png', '.webp'],
    'archive': ['.zip'],
    'preview': ['.pdf', '.mp3', '.jpg', '.jpeg', '.png'],
    'cover':   ['.jpg', '.jpeg', '.png', '.webp'],
}

# ── Tailles maximales (Mo) ──────────────────────────────────────────
MAX_MB = {
    'audio':   200,
    'video':   1024,   # 1 Go
    'book':    100,
    'image':   10,
    'archive': 500,
    'preview': 20,
    'cover':   5,
}

# ── Toutes les extensions autorisées pour un livrable numérique ─────
ALLOWED_DIGITAL_EXTENSIONS = (
    EXTENSIONS['audio']
    + EXTENSIONS['video']
    + EXTENSIONS['book']
    + EXTENSIONS['image']
    + EXTENSIONS['archive']
)


@deconstructible
class FileSizeValidator:
    """
    Validateur de taille de fichier — sérialisable en migration.

    Utiliser de préférence via la factory `validate_file_size(max_mb)`.
    """

    def __init__(self, max_mb: int):
        self.max_mb = max_mb

    def __call__(self, file):
        if not file:
            return
        try:
            size_mb = file.size / (1024 * 1024)
        except (AttributeError, OSError):
            return
        if size_mb > self.max_mb:
            raise ValidationError(
                _(
                    "Fichier trop volumineux : %(size).1f Mo. "
                    "Maximum autorisé : %(max)d Mo."
                ) % {'size': size_mb, 'max': self.max_mb}
            )

    def __eq__(self, other):
        return (
            isinstance(other, FileSizeValidator)
            and self.max_mb == other.max_mb
        )

    def __hash__(self):
        return hash(self.max_mb)


def validate_file_size(max_mb: int):
    """
    Factory : retourne un `FileSizeValidator(max_mb)` sérialisable.

    Usage :
        cover_image = models.ImageField(validators=[validate_file_size(5)])
    """
    return FileSizeValidator(max_mb)


def validate_digital_file_type(file):
    """
    Applique la bonne limite de taille à un fichier numérique
    en fonction de son extension réelle (audio/vidéo/livre/image/archive).

    Lève ValidationError si :
    - l'extension n'est pas dans ALLOWED_DIGITAL_EXTENSIONS
    - la taille dépasse MAX_MB pour le type détecté
    """
    if not file or not getattr(file, 'name', None):
        return

    import os
    ext = os.path.splitext(file.name)[1].lower()

    if ext not in ALLOWED_DIGITAL_EXTENSIONS:
        raise ValidationError(
            _("Extension « %(ext)s » non autorisée pour un fichier numérique.")
            % {'ext': ext or '(aucune)'}
        )

    for kind in ('audio', 'video', 'book', 'image', 'archive'):
        if ext in EXTENSIONS[kind]:
            max_mb = MAX_MB[kind]
            try:
                size_mb = file.size / (1024 * 1024)
            except (AttributeError, OSError):
                return
            if size_mb > max_mb:
                raise ValidationError(
                    _(
                        "Fichier %(ext)s trop volumineux : %(size).1f Mo. "
                        "Maximum autorisé pour ce type : %(max)d Mo."
                    ) % {'ext': ext, 'size': size_mb, 'max': max_mb}
                )
            return