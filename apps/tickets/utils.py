"""
IvoirPass V2 — Utilitaires pour les tickets
Génération de QR Code, PDF, et autres helpers
"""
import io
import qrcode
import qrcode.image.svg
from django.core.files.base import ContentFile
from django.conf import settings
from django.utils import timezone
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os
import logging

logger = logging.getLogger(__name__)


def generate_qr_image(ticket):
    """
    Génère l'image QR Code pour un ticket utilisateur connecté.
    """
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(ticket.qr_code_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#1B7A3E", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        filename = f"qr_{ticket.ticket_number}.png"
        ticket.qr_code_image.save(filename, ContentFile(buffer.read()), save=False)
        buffer.close()
        return True
    except Exception as e:
        logger.error(f"Erreur génération QR Code: {e}")
        return False


def generate_guest_qr_image(ticket):
    """
    Génère l'image QR Code pour un ticket invité (GuestTicket).
    """
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(ticket.qr_code_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#F47920", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        filename = f"qr_guest_{ticket.ticket_number}.png"
        ticket.qr_code_image.save(filename, ContentFile(buffer.getvalue()), save=True)
        buffer.close()
        return True
    except Exception as e:
        logger.error(f"Erreur génération QR Code invité: {e}")
        return False


def generate_ticket_pdf(ticket):
    """
    Génère un PDF pour un ticket utilisateur connecté.
    Retourne les bytes du PDF.
    """
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Police par défaut
    try:
        # Essayer d'utiliser une police système
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('DejaVu', font_path))
            p.setFont('DejaVu', 12)
    except:
        pass

    # ============================================
    # DESIGN DU BILLET
    # ============================================

    # Bordure verte
    p.setStrokeColorRGB(27/255, 122/255, 62/255)
    p.setLineWidth(2)
    p.rect(15*mm, 15*mm, width-30*mm, height-30*mm)

    # Bandeau supérieur orange
    p.setFillColorRGB(244/255, 121/255, 32/255)
    p.rect(15*mm, height-35*mm, width-30*mm, 20*mm, fill=1)

    # Titre "BILLET IVOIRPASS"
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(20*mm, height-27*mm, "🎫 BILLET IVOIRPASS")

    # Numéro de ticket
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.5, 0.5, 0.5)
    p.drawString(20*mm, height-45*mm, f"N° {ticket.ticket_number}")

    # Événement
    p.setFont("Helvetica-Bold", 16)
    p.setFillColorRGB(0, 0, 0)
    event_title = ticket.event.title[:40] + "..." if len(ticket.event.title) > 40 else ticket.event.title
    p.drawString(20*mm, height-65*mm, event_title)

    # Détails
    p.setFont("Helvetica", 11)
    y_pos = height - 80 * mm

    details = [
        ("📅 Date", ticket.event.start_date.strftime("%d %B %Y à %H:%M")),
        ("📍 Lieu", ticket.event.venue_name or ticket.event.venue_city or "En ligne"),
        ("🎟️ Type", ticket.ticket_type.name),
        ("👤 Acheteur", ticket.buyer.get_full_name() or ticket.buyer.email),
    ]

    for label, value in details:
        p.setFont("Helvetica-Bold", 10)
        p.setFillColorRGB(0.2, 0.2, 0.2)
        p.drawString(20*mm, y_pos, label)
        p.setFont("Helvetica", 10)
        p.setFillColorRGB(0, 0, 0)
        p.drawString(70*mm, y_pos, str(value))
        y_pos -= 8 * mm

    # QR Code
    if ticket.qr_code_image and hasattr(ticket.qr_code_image, 'path'):
        try:
            img_path = ticket.qr_code_image.path
            if os.path.exists(img_path):
                img = ImageReader(img_path)
                p.drawImage(img, width - 65*mm, 35*mm, width=45*mm, height=45*mm)
        except Exception as e:
            logger.error(f"Erreur inclusion QR Code: {e}")

    # Pied de page
    p.setFont("Helvetica", 8)
    p.setFillColorRGB(0.5, 0.5, 0.5)
    p.drawString(20*mm, 25*mm, f"Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')}")
    p.drawString(20*mm, 20*mm, "Présentez ce billet à l'entrée — Valable une fois")

    # Validation HMAC
    p.setFont("Helvetica", 6)
    p.setFillColorRGB(0.7, 0.7, 0.7)
    p.drawString(20*mm, 15*mm, f"HMAC: {ticket.qr_code_data[-16:]}")

    p.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_guest_ticket_pdf(ticket):
    """
    Génère un PDF pour un ticket invité (GuestTicket).
    Même design mais avec les infos de l'acheteur invité.
    """
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Police par défaut
    try:
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('DejaVu', font_path))
            p.setFont('DejaVu', 12)
    except:
        pass

    # ============================================
    # DESIGN DU BILLET INVITÉ
    # ============================================

    # Bordure orange (différenciation)
    p.setStrokeColorRGB(244/255, 121/255, 32/255)
    p.setLineWidth(2)
    p.rect(15*mm, 15*mm, width-30*mm, height-30*mm)

    # Bandeau supérieur vert
    p.setFillColorRGB(27/255, 122/255, 62/255)
    p.rect(15*mm, height-35*mm, width-30*mm, 20*mm, fill=1)

    # Titre "BILLET IVOIRPASS"
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(20*mm, height-27*mm, "🎫 BILLET IVOIRPASS")

    # Numéro de ticket
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.5, 0.5, 0.5)
    p.drawString(20*mm, height-45*mm, f"N° {ticket.ticket_number}")

    # Événement
    p.setFont("Helvetica-Bold", 16)
    p.setFillColorRGB(0, 0, 0)
    event_title = ticket.event.title[:40] + "..." if len(ticket.event.title) > 40 else ticket.event.title
    p.drawString(20*mm, height-65*mm, event_title)

    # Détails
    p.setFont("Helvetica", 11)
    y_pos = height - 80 * mm

    details = [
        ("📅 Date", ticket.event.start_date.strftime("%d %B %Y à %H:%M")),
        ("📍 Lieu", ticket.event.venue_name or ticket.event.venue_city or "En ligne"),
        ("🎟️ Type", ticket.ticket_type.name),
        ("👤 Acheteur", ticket.buyer_name or ticket.buyer_email),
    ]

    for label, value in details:
        p.setFont("Helvetica-Bold", 10)
        p.setFillColorRGB(0.2, 0.2, 0.2)
        p.drawString(20*mm, y_pos, label)
        p.setFont("Helvetica", 10)
        p.setFillColorRGB(0, 0, 0)
        p.drawString(70*mm, y_pos, str(value))
        y_pos -= 8 * mm

    # QR Code
    if ticket.qr_code_image and hasattr(ticket.qr_code_image, 'path'):
        try:
            img_path = ticket.qr_code_image.path
            if os.path.exists(img_path):
                img = ImageReader(img_path)
                p.drawImage(img, width - 65*mm, 35*mm, width=45*mm, height=45*mm)
        except Exception as e:
            logger.error(f"Erreur inclusion QR Code invité: {e}")

    # Pied de page
    p.setFont("Helvetica", 8)
    p.setFillColorRGB(0.5, 0.5, 0.5)
    p.drawString(20*mm, 25*mm, f"Généré le {timezone.now().strftime('%d/%m/%Y à %H:%M')}")
    p.drawString(20*mm, 20*mm, "Présentez ce billet à l'entrée — Valable une fois")

    # Validation HMAC
    p.setFont("Helvetica", 6)
    p.setFillColorRGB(0.7, 0.7, 0.7)
    p.drawString(20*mm, 15*mm, f"HMAC: {ticket.qr_code_data[-16:]}")

    p.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_event_ticket_pdf(event, ticket_type, buyer_name, buyer_email, ticket_number, qr_data):
    """
    Génère un PDF de ticket à partir de données brutes.
    Utilisé pour les tests ou générations sans modèle.
    """
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Bordure verte
    p.setStrokeColorRGB(27/255, 122/255, 62/255)
    p.setLineWidth(2)
    p.rect(15*mm, 15*mm, width-30*mm, height-30*mm)

    # Bandeau supérieur orange
    p.setFillColorRGB(244/255, 121/255, 32/255)
    p.rect(15*mm, height-35*mm, width-30*mm, 20*mm, fill=1)

    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(20*mm, height-27*mm, "🎫 BILLET IVOIRPASS")

    p.setFont("Helvetica-Bold", 16)
    p.setFillColorRGB(0, 0, 0)
    p.drawString(20*mm, height-65*mm, event.title[:40])

    p.setFont("Helvetica", 11)
    y_pos = height - 80 * mm

    details = [
        ("📅 Date", event.start_date.strftime("%d %B %Y à %H:%M")),
        ("📍 Lieu", event.venue_name or event.venue_city or "En ligne"),
        ("🎟️ Type", ticket_type.name if ticket_type else "Standard"),
        ("👤 Acheteur", buyer_name or buyer_email),
    ]

    for label, value in details:
        p.setFont("Helvetica-Bold", 10)
        p.setFillColorRGB(0.2, 0.2, 0.2)
        p.drawString(20*mm, y_pos, label)
        p.setFont("Helvetica", 10)
        p.setFillColorRGB(0, 0, 0)
        p.drawString(70*mm, y_pos, str(value))
        y_pos -= 8 * mm

    p.setFont("Helvetica", 8)
    p.setFillColorRGB(0.5, 0.5, 0.5)
    p.drawString(20*mm, 25*mm, f"Billet {ticket_number}")

    p.save()
    buffer.seek(0)
    return buffer.getvalue()

def generate_guest_ticket_pdf(ticket):
    """
    Génère le PDF d'un billet IvoirPass pour un acheteur sans compte.
    Même design que le billet classique.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    import io

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    event       = ticket.event
    ticket_type = ticket.ticket_type
    buyer_name  = ticket.buyer_name
    buyer_email = ticket.buyer_email

    GREEN  = colors.HexColor('#1B7A3E')
    ORANGE = colors.HexColor('#F47920')
    DARK   = colors.HexColor('#1a1a2e')
    LIGHT  = colors.HexColor('#f5f7fa')

    # Fond
    c.setFillColor(LIGHT)
    c.rect(0, 0, width, height, fill=True, stroke=False)

    # Bande supérieure
    c.setFillColor(DARK)
    c.rect(0, height - 120, width, 120, fill=True, stroke=False)
    c.setFillColor(ORANGE)
    c.rect(0, height - 123, width, 3, fill=True, stroke=False)

    # Logo
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(30*mm, height - 55, "Ivoir")
    c.setFillColor(ORANGE)
    c.drawString(30*mm + 70, height - 55, "Pass")
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 10)
    c.drawString(30*mm, height - 72, "Votre billet officiel")

    # Numéro billet
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.white)
    c.drawRightString(width - 20*mm, height - 50, f"N° {ticket.ticket_number}")

    # Titre événement
    y = height - 165
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 20)
    title = event.title[:45] + "..." if len(event.title) > 45 else event.title
    c.drawString(30*mm, y, title)
    y -= 28

    c.setStrokeColor(GREEN)
    c.setLineWidth(2)
    c.line(30*mm, y, width - 30*mm, y)
    y -= 18

    def info_block(label, value, x, y_pos):
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor('#6c757d'))
        c.drawString(x, y_pos, label.upper())
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(DARK)
        val = str(value)[:30] + "..." if len(str(value)) > 30 else str(value)
        c.drawString(x, y_pos - 14, val)

    col1_x = 30*mm
    col2_x = width / 2

    info_block("Date", event.start_date.strftime("%d %B %Y"), col1_x, y)
    info_block("Heure", event.start_date.strftime("%H h %M"), col2_x, y)
    y -= 38

    info_block("Lieu", event.venue_name or event.venue_city or "—", col1_x, y)
    info_block("Ville", event.venue_city, col2_x, y)
    y -= 38

    info_block("Type de billet", ticket_type.name, col1_x, y)
    info_block("Prix",
               f"{ticket_type.price:,.0f} FCFA" if ticket_type.price > 0 else "Gratuit",
               col2_x, y)
    y -= 38

    info_block("Acheteur", buyer_name, col1_x, y)
    info_block("Email",    buyer_email[:30], col2_x, y)
    y -= 50

    # Séparateur
    c.setStrokeColor(colors.HexColor('#dee2e6'))
    c.setLineWidth(1)
    c.setDash(4, 4)
    c.line(30*mm, y, width - 30*mm, y)
    c.setDash()
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor('#aaa'))
    c.drawCentredString(width/2, y + 5, "✂  Détacher ici  ✂")
    y -= 30

    # QR Code
    qr_size = 100
    if ticket.qr_code_image:
        try:
            qr_img = ImageReader(ticket.qr_code_image.path)
            qr_x   = width/2 - qr_size/2
            c.drawImage(qr_img, qr_x, y - qr_size, qr_size, qr_size)
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(DARK)
    c.drawCentredString(width/2, y - qr_size - 16, ticket.ticket_number)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor('#6c757d'))
    c.drawCentredString(width/2, y - qr_size - 28,
                        "Présentez ce QR Code à l'entrée — aucune impression nécessaire")

    # Pied de page
    c.setFillColor(DARK)
    c.rect(0, 0, width, 35, fill=True, stroke=False)
    c.setFillColor(ORANGE)
    c.rect(0, 35, width, 2, fill=True, stroke=False)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.white)
    c.drawCentredString(width/2, 13,
                        "IvoirPass — www.ivoirpass.com | infos@mks-soft-technologies.com")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()