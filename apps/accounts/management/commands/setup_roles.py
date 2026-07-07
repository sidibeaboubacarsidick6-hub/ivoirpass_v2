"""
Commande Django : crée les groupes de rôles administrateurs
Usage : python manage.py setup_roles
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


class Command(BaseCommand):
    help = 'Crée les groupes Admin, Financier, Modérateur, Support avec leurs permissions'

    def handle(self, *args, **options):
        # Admin (tous les droits)
        admin_group, _ = Group.objects.get_or_create(name='Admin Plateforme')
        admin_group.permissions.set(Permission.objects.all())

        # Financier
        finance_group, _ = Group.objects.get_or_create(name='Financier')
        finance_perms = Permission.objects.filter(
            codename__in=[
                'view_withdrawalrequest', 'change_withdrawalrequest',
                'view_payment', 'view_wallettransaction',
                'view_organizerwallet',
            ]
        )
        finance_group.permissions.set(finance_perms)

        # Modérateur
        moderator_group, _ = Group.objects.get_or_create(name='Modérateur')
        moderator_perms = Permission.objects.filter(
            codename__in=[
                'view_event', 'change_event',
                'view_product', 'change_product',
                'view_customuser', 'change_customuser',
            ]
        )
        moderator_group.permissions.set(moderator_perms)

        # Support
        support_group, _ = Group.objects.get_or_create(name='Support')
        support_perms = Permission.objects.filter(
            codename__in=[
                'view_order', 'view_ticket', 'view_productorder',
                'view_customuser',
            ]
        )
        support_group.permissions.set(support_perms)

        self.stdout.write(self.style.SUCCESS('✅ Groupes créés : Admin, Financier, Modérateur, Support'))
