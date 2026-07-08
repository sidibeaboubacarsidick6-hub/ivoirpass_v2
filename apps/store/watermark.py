"""
IvoirPass V2 — Service de filigrane numérique
Ajoute le nom de l'acheteur et la référence de commande dans les PDF.
"""
import io
import os
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from django.conf import settings


def add_watermark_to_pdf(input_file, buyer_name, order_number):
    """
    Ajoute un filigrane discret sur chaque page du PDF.
    Retourne un BytesIO contenant le PDF filigrané.
    """
    # Créer le filigrane (texte transparent)
    watermark_buffer = io.BytesIO()
    c = canvas.Canvas(watermark_buffer)

    watermark_text = f"ACHETÉ PAR : {buyer_name} — Commande : {order_number} — IvoirPass"
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.6, 0.6, 0.6, alpha=0.3)  # Gris clair, semi-transparent

    # Position : en bas à droite, incliné
    c.saveState()
    c.translate(300, 30)
    c.rotate(0)
    c.drawString(0, 0, watermark_text)
    c.restoreState()

    # Filigrane diagonal au centre
    c.saveState()
    c.setFont("Helvetica", 20)
    c.setFillColorRGB(0.8, 0.8, 0.8, alpha=0.08)
    c.translate(150, 400)
    c.rotate(45)
    c.drawString(0, 0, f"{buyer_name} — {order_number}")
    c.restoreState()

    c.save()
    watermark_buffer.seek(0)
    watermark_pdf = PdfReader(watermark_buffer)

    # Appliquer à toutes les pages
    reader = PdfReader(input_file)
    writer = PdfWriter()

    for page in reader.pages:
        page.merge_page(watermark_pdf.pages[0])
        writer.add_page(page)

    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    output_buffer.seek(0)

    return output_buffer


def add_watermark_to_epub(input_file, buyer_name, order_number):
    """
    Ajoute un filigrane texte dans un fichier EPUB.
    Note : modifie le fichier OPF pour ajouter les métadonnées d'achat.
    Retourne un BytesIO contenant l'EPUB modifié.
    """
    import zipfile
    from xml.etree import ElementTree as ET

    output_buffer = io.BytesIO()

    with zipfile.ZipFile(input_file, 'r') as zin:
        with zipfile.ZipFile(output_buffer, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                content = zin.read(item.filename)

                # Ajouter les métadonnées dans le fichier .opf
                if item.filename.endswith('.opf'):
                    try:
                        ET.register_namespace('', 'http://www.idpf.org/2007/opf')
                        ET.register_namespace('dc', 'http://purl.org/dc/elements/1.1/')
                        root = ET.fromstring(content)
                        ns = {'dc': 'http://purl.org/dc/elements/1.1/'}

                        # Ajouter les métadonnées d'achat
                        metadata = root.find('.//{http://www.idpf.org/2007/opf}metadata')
                        if metadata is not None:
                            rights = ET.SubElement(metadata, '{http://purl.org/dc/elements/1.1/}rights')
                            rights.text = f"Acheté par {buyer_name} — Commande {order_number} — IvoirPass — Usage personnel uniquement"

                        content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                    except Exception:
                        pass

                zout.writestr(item, content)

    output_buffer.seek(0)
    return output_buffer


def add_watermark(file_path, buyer_name, order_number):
    """
    Détecte le type de fichier et applique le filigrane approprié.
    Retourne (BytesIO, filename) ou (None, None) si type non supporté.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.pdf':
        watermarked = add_watermark_to_pdf(file_path, buyer_name, order_number)
        return watermarked, os.path.basename(file_path)

    elif ext in ['.epub', '.mobi']:
        watermarked = add_watermark_to_epub(file_path, buyer_name, order_number)
        return watermarked, os.path.basename(file_path)

    # Pour les autres types (MP3, images...), on laisse passer sans filigrane
    return None, None
