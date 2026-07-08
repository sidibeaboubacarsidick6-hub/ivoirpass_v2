"""
IvoirPass V2 — Vues du compte utilisateur
"""
from django.core.cache import cache
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from .models import CustomUser, UserAddress
from .forms import ProfileEditForm, OrganizerProfileForm, UserAddressForm


def home(request):
    """Page d'accueil avec événements réels et pagination."""
    from apps.events.models import Event
    from django.utils import timezone
    from django.core.paginator import Paginator

    now = timezone.now()

    # Cache : événements mis en avant (5 minutes)
    cache_key_featured = 'home_featured_events'
    featured_events = cache.get(cache_key_featured)
    if featured_events is None:
        featured_events = list(Event.objects.filter(
            status='published',
            start_date__gte=now,
        ).select_related('category').order_by('start_date')[:6])
        cache.set(cache_key_featured, featured_events, 300)

    # Pagination : cache par page (5 minutes)
    page_number = request.GET.get('page', 1)
    cache_key_upcoming = f'home_upcoming_events_page_{page_number}'
    upcoming_events = cache.get(cache_key_upcoming)
    if upcoming_events is None:
        upcoming_qs = Event.objects.filter(
            status='published',
            start_date__gte=now,
        ).select_related('category', 'organizer').order_by('start_date')
        paginator = Paginator(upcoming_qs, 6)
        upcoming_events = paginator.get_page(page_number)
        cache.set(cache_key_upcoming, upcoming_events, 300)

    return render(request, 'pages/home.html', {
        'featured_events': featured_events,
        'upcoming_events': upcoming_events,
    })


@login_required
def profile(request):
    """Page profil — vue en lecture."""
    addresses = request.user.addresses.all()
    return render(request, 'pages/profile.html', {
        'addresses': addresses,
    })


def profile_edit(request):
    """Modification du profil utilisateur."""
    user = request.user
    profile_form   = ProfileEditForm(instance=user)
    organizer_form = OrganizerProfileForm(instance=user)

    if request.method == 'POST':
        profile_form = ProfileEditForm(
            request.POST, request.FILES, instance=user
        )
        organizer_form = OrganizerProfileForm(
            request.POST, request.FILES, instance=user
        )
        profile_ok   = profile_form.is_valid()
        organizer_ok = organizer_form.is_valid() if user.is_organizer else True

        if profile_ok and organizer_ok:
            profile_form.save()
            if user.is_organizer:
                organizer_form.save()

            # Notifier les admins si KYC present
            if user.is_organizer and not user.is_organizer_verified:
                from apps.accounts.models import CustomUser
                fresh_user = CustomUser.objects.get(pk=user.pk)

                if fresh_user.kyc_identity_doc or fresh_user.kyc_proof_of_address or fresh_user.kyc_business_doc:
                    from apps.notifications.models import AdminNotification
                    AdminNotification.objects.create(
                        type='fraud_alert',
                        title='KYC en attente de verification',
                        message=(
                            f"L'organisateur {fresh_user.get_full_name()} ({fresh_user.email}) "
                            f"a soumis ses documents KYC.\n\n"
                            f"Piece d'identite : {'Oui' if fresh_user.kyc_identity_doc else 'Non'}\n"
                            f"Justificatif domicile : {'Oui' if fresh_user.kyc_proof_of_address else 'Non'}\n"
                            f"Document pro : {'Oui' if fresh_user.kyc_business_doc else 'Non'}\n\n"
                            f"Verifiez dans le back-office : /admin/accounts/customuser/{fresh_user.pk}/change/"
                        ),
                        reference=f'kyc-{fresh_user.pk}',
                    )
                    messages.success(request, "Votre demande de verification a ete envoyee.")
                    return redirect('accounts:profile')

            messages.success(request, "Votre profil a ete mis a jour avec succes.")
            return redirect('accounts:profile')
        else:
            messages.error(request, "Veuillez corriger les erreurs ci-dessous.")

    return render(request, 'pages/profile_edit.html', {
        'profile_form':   profile_form,
        'organizer_form': organizer_form,
    })

@login_required
def change_password(request):
    """Changement de mot de passe."""
    form = PasswordChangeForm(request.user)

    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Mot de passe modifié avec succès.")
            return redirect('accounts:profile')
        else:
            messages.error(request, "Veuillez corriger les erreurs.")

    return render(request, 'pages/change_password.html', {'form': form})


@login_required
def address_list(request):
    """Liste des adresses de livraison."""
    addresses = request.user.addresses.all()
    form = UserAddressForm()

    if request.method == 'POST':
        form = UserAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            messages.success(request, "Adresse ajoutée avec succès.")
            return redirect('accounts:addresses')

    return render(request, 'pages/addresses.html', {
        'addresses': addresses,
        'form': form,
    })


@login_required
def address_delete(request, pk):
    """Suppression d'une adresse."""
    address = get_object_or_404(UserAddress, pk=pk, user=request.user)
    if request.method == 'POST':
        address.delete()
        messages.success(request, "Adresse supprimée.")
    return redirect('accounts:addresses')


def post_login_redirect(request):
    """Redirige selon le rôle après connexion."""
    user = request.user
    if not user.is_authenticated:
        return redirect('home')

    if user.is_organizer or user.is_platform_admin:
        return redirect('dashboard:index')
    elif user.is_scanner_agent:
        return redirect('scanner:index')
    else:
        return redirect('home')


@login_required
def my_orders_history(request):
    """Espace confiance acheteur — historique complet."""
    from apps.tickets.models import Order, Ticket
    from apps.store.models import ProductOrder

    ticket_orders = Order.objects.filter(
        buyer=request.user
    ).prefetch_related('items__ticket_type__event', 'items__tickets').order_by('-created_at')

    product_orders = ProductOrder.objects.filter(
        buyer=request.user
    ).select_related('product').order_by('-created_at')

    return render(request, 'pages/my_orders_history.html', {
        'ticket_orders': ticket_orders,
        'product_orders': product_orders,
    })


@login_required
def download_invoice_pdf(request, order_type, order_number):
    """Génère une facture PDF pour une commande."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from io import BytesIO
    from django.http import HttpResponse

    if order_type == 'ticket':
        from apps.tickets.models import Order
        order = get_object_or_404(Order, order_number=order_number, buyer=request.user)
        items = order.items.select_related('ticket_type__event')
        product_name = ", ".join(f"{i.ticket_type.event.title} — {i.ticket_type.name} x{i.quantity}" for i in items)
    else:
        from apps.store.models import ProductOrder
        order = get_object_or_404(ProductOrder, order_number=order_number, buyer=request.user)
        product_name = f"{order.product.name} x{order.quantity}"

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 18)
    p.drawString(20*mm, height - 20*mm, "FACTURE")
    p.setFont("Helvetica", 10)
    p.drawString(20*mm, height - 30*mm, f"N° {order.order_number}")
    p.drawString(20*mm, height - 36*mm, f"Date : {order.created_at.strftime('%d/%m/%Y')}")
    p.drawString(20*mm, height - 42*mm, f"Client : {request.user.get_full_name()}")
    p.drawString(20*mm, height - 48*mm, f"Email : {request.user.email}")

    p.line(20*mm, height - 54*mm, width - 20*mm, height - 54*mm)

    p.setFont("Helvetica-Bold", 10)
    p.drawString(20*mm, height - 62*mm, "Produit")
    p.drawString(120*mm, height - 62*mm, "Total (FCFA)")

    p.setFont("Helvetica", 10)
    p.drawString(20*mm, height - 70*mm, product_name[:60])
    p.drawString(120*mm, height - 70*mm, f"{int(order.total):,}")

    p.line(20*mm, height - 76*mm, width - 20*mm, height - 76*mm)

    p.setFont("Helvetica-Bold", 12)
    p.drawString(120*mm, height - 84*mm, f"TOTAL : {int(order.total):,} FCFA")

    p.setFont("Helvetica", 8)
    p.drawString(20*mm, 20*mm, "IvoirPass — MKS Soft Technologies — Abidjan, Côte d'Ivoire")

    p.showPage()
    p.save()
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="facture_{order.order_number}.pdf"'
    return response