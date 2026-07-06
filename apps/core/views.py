from django.shortcuts import render


def how_it_works(request):
    """Page Comment ça marche"""
    return render(request, 'pages/how_it_works.html')


def faq(request):
    """Page FAQ"""
    return render(request, 'pages/faq.html')


def contact(request):
    """Page Contact"""
    return render(request, 'pages/contact.html')


def report_problem(request):
    """Page Signaler un problème"""
    return render(request, 'pages/report_problem.html')


def cgu(request):
    """Conditions d'utilisation"""
    return render(request, 'pages/cgu.html')


def privacy_policy(request):
    """Politique de confidentialité"""
    return render(request, 'pages/privacy_policy.html')