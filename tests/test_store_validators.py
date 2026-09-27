"""
IvoirPass V2 — Tests des validateurs boutique (étape 1).
Couvre les cas #1, #2, #3, #8, #9 de la liste chantier.
"""
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.validators import FileExtensionValidator, MinValueValidator

from apps.store.models import Product
from apps.store.validators import (
    EXTENSIONS, MAX_MB, ALLOWED_DIGITAL_EXTENSIONS,
    validate_file_size, validate_digital_file_type,
)


def _uploaded(name, size_mb):
    """Crée un fichier en mémoire de size_mb Mo."""
    return SimpleUploadedFile(name, b"x" * int(size_mb * 1024 * 1024))


class FileSizeValidatorTests(TestCase):
    """Tests #2, #3 : taille de fichier."""

    def test_size_under_limit_ok(self):
        v = validate_file_size(200)
        v(_uploaded("ok.mp3", 5))  # ne lève pas

    def test_size_over_limit_raises(self):
        v = validate_file_size(200)
        with self.assertRaises(ValidationError):
            v(_uploaded("big.mp3", 250))

    def test_size_none_ignored(self):
        v = validate_file_size(5)
        v(None)  # ne lève pas


class DigitalFileTypeValidatorTests(TestCase):
    """Test #1 : extension + type réel."""

    def test_exe_rejected(self):
        with self.assertRaises(ValidationError):
            validate_digital_file_type(_uploaded("virus.exe", 0.01))

    def test_mp3_50mb_accepted(self):
        validate_digital_file_type(_uploaded("track.mp3", 50))

    def test_mp3_250mb_rejected(self):
        """250 Mo > 200 Mo max pour audio."""
        with self.assertRaises(ValidationError):
            validate_digital_file_type(_uploaded("big.mp3", 250))

    def test_pdf_150mb_rejected(self):
        """150 Mo > 100 Mo max pour book."""
        with self.assertRaises(ValidationError):
            validate_digital_file_type(_uploaded("book.pdf", 150))

    def test_zip_600mb_rejected(self):
        """600 Mo > 500 Mo max pour archive."""
        with self.assertRaises(ValidationError):
            validate_digital_file_type(_uploaded("album.zip", 600))


class ModelFieldValidatorsTests(TestCase):
    """Vérifie que les validateurs sont bien attachés aux champs."""

    def _validators_for(self, field_name):
        return list(Product._meta.get_field(field_name).validators)

    def test_price_has_min_value_validator(self):
        has_min = any(
            isinstance(v, MinValueValidator) and v.limit_value == 500
            for v in self._validators_for('price')
        )
        self.assertTrue(has_min, "price doit avoir MinValueValidator(500)")

    def test_price_300_rejected(self):
        for v in self._validators_for('price'):
            if isinstance(v, MinValueValidator):
                with self.assertRaises(ValidationError):
                    v(300)
                return
        self.fail("MinValueValidator absent sur price")

    def test_price_500_accepted(self):
        for v in self._validators_for('price'):
            if isinstance(v, MinValueValidator):
                v(500)  # ne lève pas
                return
        self.fail("MinValueValidator absent sur price")

    def test_price_physical_has_min_validator(self):
        has_min = any(
            isinstance(v, MinValueValidator) and v.limit_value == 500
            for v in self._validators_for('price_physical')
        )
        self.assertTrue(has_min)

    def test_price_digital_has_min_validator(self):
        has_min = any(
            isinstance(v, MinValueValidator) and v.limit_value == 500
            for v in self._validators_for('price_digital')
        )
        self.assertTrue(has_min)

    def test_cover_image_extensions(self):
        ext_validators = [
            v for v in self._validators_for('cover_image')
            if isinstance(v, FileExtensionValidator)
        ]
        self.assertEqual(len(ext_validators), 1)
        self.assertEqual(
            sorted(ext_validators[0].allowed_extensions),
            sorted(EXTENSIONS['cover'])
        )

    def test_digital_file_has_type_validator(self):
        has_type = any(
            getattr(v, '__name__', '') == 'validate_digital_file_type'
            for v in self._validators_for('digital_file')
        )
        self.assertTrue(
            has_type,
            "digital_file doit avoir validate_digital_file_type"
        )


class ProductInfoLineTests(TestCase):
    """Test #5 : label InfoLine + help text."""

    def test_short_description_label_is_infoline(self):
        field = Product._meta.get_field('short_description')
        self.assertEqual(str(field.verbose_name), 'InfoLine')

    def test_short_description_help_text(self):
        field = Product._meta.get_field('short_description')
        self.assertIn('contact', field.help_text.lower())