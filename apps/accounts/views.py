"""
IvoirPass V2 — Vues du compte utilisateur
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from .models import CustomUser, UserAddress
from .forms import ProfileEditForm, OrganizerProfileForm, UserAddressForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def home(request):
    """Page d'accueil avec événements réels et pagination."""
    from apps.events.models import Event
    from django.utils import timezone
    from django.core.paginator import Paginator

    now = timezone.now()

    featured_events = Event.objects.filter(
        status='published',
        start_date__gte=now,
    ).select_related('category').order_by('start_date')[:6]

    upcoming_qs = Event.objects.filter(
        status='published',
        start_date__gte=now,
    ).select_related('category', 'organizer').order_by('start_date')

    paginator   = Paginator(upcoming_qs, 6)
    page_number = request.GET.get('page', 1)
    upcoming_events = paginator.get_page(page_number)

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


@login_required
def profile_edit(request):
    """Modification du profil utilisateur."""
    user = request.user

    # Deux formulaires : profil de base + organisateur
    profile_form    = ProfileEditForm(instance=user)
    organizer_form  = OrganizerProfileForm(instance=user)

    if request.method == 'POST':
        profile_form = ProfileEditForm(
            request.POST, request.FILES, instance=user
        )
        organizer_form = OrganizerProfileForm(
            request.POST, request.FILES, instance=user
        )

        profile_ok    = profile_form.is_valid()
        organizer_ok  = organizer_form.is_valid() if user.is_organizer else True

        if profile_ok and organizer_ok:
            profile_form.save()
            if user.is_organizer:
                organizer_form.save()
            messages.success(request, "Votre profil a été mis à jour avec succès.")
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