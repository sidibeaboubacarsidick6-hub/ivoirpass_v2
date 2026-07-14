"""
Test d'audit — Validation de taille des fichiers KYC (Phase 2 du script MVP).
Vérifie qu'un fichier de plus de 5 Mo est bien rejeté, et qu'un fichier
de taille normale passe sans problème.

Lancer :
    DJANGO_SETTINGS_MODULE=config.settings.testlocal python manage.py test tests.test_kyc_file_size_audit -v 2
"""
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import CustomUser, validate_kyc_file_size, KYC_MAX_FILE_SIZE_BYTES


class KYCFileSizeValidatorTests(TestCase):

    def test_fichier_trop_lourd_rejete(self):
        fichier_trop_gros = SimpleUploadedFile(
            "piece_identite.pdf",
            b"x" * (KYC_MAX_FILE_SIZE_BYTES + 1),
            content_type="application/pdf",
        )
        with self.assertRaises(ValidationError):
            validate_kyc_file_size(fichier_trop_gros)

    def test_fichier_taille_normale_accepte(self):
        fichier_ok = SimpleUploadedFile(
            "piece_identite.pdf",
            b"x" * (1024 * 1024),  # 1 Mo
            content_type="application/pdf",
        )
        try:
            validate_kyc_file_size(fichier_ok)
        except ValidationError:
            self.fail("Un fichier de 1 Mo ne devrait pas être rejeté (limite = 5 Mo)")

    def test_fichier_exactement_5mo_accepte(self):
        fichier_limite = SimpleUploadedFile(
            "piece_identite.pdf",
            b"x" * KYC_MAX_FILE_SIZE_BYTES,
            content_type="application/pdf",
        )
        try:
            validate_kyc_file_size(fichier_limite)
        except ValidationError:
            self.fail("Un fichier de exactement 5 Mo ne devrait pas être rejeté")

    def test_validateur_applique_sur_les_3_champs_kyc(self):
        """Vérifie que le validateur est bien branché sur les 3 champs, pas juste 1."""
        for field_name in ['kyc_identity_doc', 'kyc_proof_of_address', 'kyc_business_doc']:
            field = CustomUser._meta.get_field(field_name)
            self.assertIn(
                validate_kyc_file_size, field.validators,
                f"validate_kyc_file_size manquant sur le champ {field_name}"
            )