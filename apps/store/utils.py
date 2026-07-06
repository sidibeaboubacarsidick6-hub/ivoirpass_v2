"""
IvoirPass V2 — Utilitaires boutique
"""
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def send_download_link_email(order):
    """
    Envoie un email à l'acheteur avec les liens de téléchargement.
    """
    if not order.buyer.email:
        return

    download_links = order.download_links.all()
    if not download_links.exists():
        return

    product = order.product
    base_url = 'https://revengeless-unfervent-deandrea.ngrok-free.dev'

    subject = f"📥 Téléchargez votre produit — {product.name}"

    context = {
        'order': order,
        'product': product,
        'download_links': download_links,
        'buyer': order.buyer,
        'base_url': base_url,
    }

    html_content = render_to_string('emails/store_download_email.html', context)
    text_content = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email='IvoirPass Boutique <noreply@ivoirpass.com>',
        to=[order.buyer.email],
    )
    email.attach_alternative(html_content, "text/html")

    try:
        email.send(fail_silently=True)
    except Exception:
        pass