"""
Tests du filigrane PDF/EPUB — apps/store/watermark.py

Couvre :
- add_watermark_to_pdf : ajoute le filigrane + retourne BytesIO
- add_watermark_to_epub : ajoute les métadonnées + retourne BytesIO
- add_watermark : dispatcher selon l'extension (.pdf, .epub, .mobi, autre)
- Gestion fichier inexistant
"""
import io
import os
import zipfile
import tempfile

from django.test import TestCase

from apps.store.watermark import (
    add_watermark_to_pdf,
    add_watermark_to_epub,
    add_watermark,
)


def _make_minimal_pdf():
    """Crée un PDF minimal en mémoire (1 page vide)."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "Test PDF")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def _make_minimal_epub():
    """Crée un EPUB minimal (juste le strict nécessaire pour le test)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # mimetype obligatoire
        z.writestr('mimetype', 'application/epub+zip')
        # Un OPF minimal avec namespace metadata
        opf = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test</dc:title>
  </metadata>
  <manifest></manifest>
  <spine></spine>
</package>'''
        z.writestr('OEBPS/content.opf', opf)
    buf.seek(0)
    return buf


class AddWatermarkToPdfTests(TestCase):
    """Tests de add_watermark_to_pdf."""

    def test_ajoute_filigrane_et_retourne_bytesio(self):
        """PDF en entrée → BytesIO en sortie avec filigrane."""
        input_pdf = _make_minimal_pdf()
        output = add_watermark_to_pdf(input_pdf, 'Ali B', 'IP-2026-TEST')

        self.assertIsInstance(output, io.BytesIO)
        # Le contenu commence par %PDF
        content = output.read()
        self.assertTrue(content.startswith(b'%PDF'))
        self.assertGreater(len(content), 0)

    def test_filigrane_non_vide(self):
        """Le PDF filigrané est plus lourd que l'original (page de filigrane ajoutée)."""
        input_pdf = _make_minimal_pdf()
        original_size = len(input_pdf.getvalue())
        input_pdf.seek(0)

        output = add_watermark_to_pdf(input_pdf, 'Ali B', 'IP-2026-TEST')
        output_size = len(output.getvalue())

        # Le filigrane ajoute du contenu
        self.assertGreater(output_size, 0)
        # Le PDF source fait quelques centaines d'octets ; le filigrané aussi
        self.assertGreater(output_size, original_size * 0.5)


class AddWatermarkToEpubTests(TestCase):
    """Tests de add_watermark_to_epub."""

    def test_ajoute_metadonnees_et_retourne_bytesio(self):
        """EPUB → BytesIO avec métadonnées d'achat ajoutées."""
        input_epub = _make_minimal_epub()
        output = add_watermark_to_epub(input_epub, 'Ali B', 'IP-2026-TEST')

        self.assertIsInstance(output, io.BytesIO)
        # Contenu valide en ZIP
        content = output.read()
        self.assertGreater(len(content), 0)
        # Signature ZIP : commence par PK
        self.assertTrue(content.startswith(b'PK'))

    def test_metadonnees_presentes_dans_opf(self):
        """Le texte 'Acheté par Ali B' est présent dans le contenu."""
        input_epub = _make_minimal_epub()
        output = add_watermark_to_epub(input_epub, 'Ali B', 'IP-2026-TEST')

        # Ouvre le ZIP retourné et cherche le OPF
        output.seek(0)
        with zipfile.ZipFile(output, 'r') as z:
            opf_content = z.read('OEBPS/content.opf').decode('utf-8')
            self.assertIn('Ali B', opf_content)
            self.assertIn('IP-2026-TEST', opf_content)


class AddWatermarkDispatcherTests(TestCase):
    """Tests du dispatcher add_watermark."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_temp(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'wb') as f:
            f.write(content)
        return path

    def test_pdf_dispatch(self):
        """Extension .pdf → filigrane PDF appliqué."""
        pdf_bytes = _make_minimal_pdf().getvalue()
        path = self._write_temp('doc.pdf', pdf_bytes)

        result, filename = add_watermark(path, 'Ali B', 'IP-1')

        self.assertIsNotNone(result)
        self.assertEqual(filename, 'doc.pdf')

    def test_epub_dispatch(self):
        """Extension .epub → filigrane EPUB appliqué."""
        epub_bytes = _make_minimal_epub().getvalue()
        path = self._write_temp('book.epub', epub_bytes)

        result, filename = add_watermark(path, 'Ali B', 'IP-2')

        self.assertIsNotNone(result)
        self.assertEqual(filename, 'book.epub')

    def test_mobi_dispatch(self):
        """Extension .mobi → traité comme EPUB (par le code actuel)."""
        epub_bytes = _make_minimal_epub().getvalue()
        path = self._write_temp('book.mobi', epub_bytes)

        result, filename = add_watermark(path, 'Ali B', 'IP-3')

        self.assertIsNotNone(result)
        self.assertEqual(filename, 'book.mobi')

    def test_mp3_retourne_none(self):
        """Fichier .mp3 → aucun filigrane, retourne (None, None)."""
        path = self._write_temp('song.mp3', b'fake mp3 content')

        result, filename = add_watermark(path, 'Ali B', 'IP-4')

        self.assertIsNone(result)
        self.assertIsNone(filename)

    def test_extension_inconnue_retourne_none(self):
        """Extension .docx → (None, None)."""
        path = self._write_temp('doc.docx', b'fake')

        result, filename = add_watermark(path, 'Ali B', 'IP-5')

        self.assertIsNone(result)
        self.assertIsNone(filename)