from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('comment-ca-marche/', views.how_it_works, name='how_it_works'),
    path('faq/', views.faq, name='faq'),
    path('contact/', views.contact, name='contact'),
    path('signaler-un-probleme/', views.report_problem, name='report_problem'),
    path('conditions-utilisation/', views.cgu, name='cgu'),
    path('politique-confidentialite/', views.privacy_policy, name='privacy_policy'),
]