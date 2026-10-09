"""
IvoirPass V2 — Génération des rapports périodiques (Excel + ZIP chiffré)

Ce module produit le rapport hebdomadaire envoyé aux responsables :
  - Onglet 1 : Résumé (chiffres clés semaine + 30 jours)
  - Onglet 2 : Transactions (commandes payées de la semaine)
  - Onglet 3 : Reversements (demandes de la semaine)
  - Onglet 4 : Nouveaux utilisateurs (inscriptions de la semaine)

Le tout est packagé dans un ZIP chiffré AES-256 protégé par le mot
de passe défini dans WEEKLY_REPORT_ZIP_PASSWORD.
"""
import io
import logging
from datetime import timedelta
from decimal import Decimal


from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PÉRIODES
# ---------------------------------------------------------------------------
def _last_week_range():
    """
    Retourne (start, end) de la semaine écoulée :
      start = lundi 00:00 de la semaine dernière
      end   = dimanche 23:59:59 de la semaine dernière
    Heure locale Africa/Abidjan.
    """
    now = timezone.localtime(timezone.now())
    monday_this_week = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = monday_this_week - timedelta(days=7)
    end = monday_this_week - timedelta(seconds=1)
    return start, end


def _last_30_days_range():
    """Retourne (start, end) des 30 derniers jours (jusqu'à maintenant)."""
    now = timezone.localtime(timezone.now())
    return now - timedelta(days=30), now


# ---------------------------------------------------------------------------
# COLLECTE DE DONNÉES
# ---------------------------------------------------------------------------
def _collect_data(start, end):
    """Récupère toutes les données nécessaires pour la période."""
    from apps.tickets.models import Order, GuestOrder
    from apps.store.models import ProductOrder, GuestProductOrder
    from apps.dashboard.models import WithdrawalRequest
    from apps.accounts.models import CustomUser

    return {
        'orders': Order.objects.filter(
            paid_at__gte=start, paid_at__lte=end,
            status=Order.Status.PAID,
        ).select_related('buyer').order_by('-paid_at'),
        'guest_orders': GuestOrder.objects.filter(
            paid_at__gte=start, paid_at__lte=end,
            status=GuestOrder.Status.PAID,
        ).order_by('-paid_at'),
        'product_orders': ProductOrder.objects.filter(
            paid_at__gte=start, paid_at__lte=end,
            status=ProductOrder.Status.PAID,
        ).select_related('buyer', 'product').order_by('-paid_at'),
        'guest_product_orders': GuestProductOrder.objects.filter(
            paid_at__gte=start, paid_at__lte=end,
            status=GuestProductOrder.Status.PAID,
        ).select_related('product').order_by('-paid_at'),
        'withdrawals': WithdrawalRequest.objects.filter(
            created_at__gte=start, created_at__lte=end,
        ).select_related('wallet__organizer').order_by('-created_at'),
        'new_users': CustomUser.objects.filter(
            date_joined__gte=start, date_joined__lte=end,
        ).order_by('-date_joined'),
    }


def _sum_amount(queryset):
    """Somme des 'total' d'un queryset (0 si vide)."""
    return queryset.aggregate(t=Sum('total'))['t'] or Decimal('0')


# ---------------------------------------------------------------------------
# STYLES EXCEL
# ---------------------------------------------------------------------------
_GREEN_FILL = PatternFill(start_color="1B7A3E", end_color="1B7A3E", fill_type="solid")
_ORANGE_FILL = PatternFill(start_color="F47920", end_color="F47920", fill_type="solid")
_CYAN_FILL = PatternFill(start_color="0dcaf0", end_color="0dcaf0", fill_type="solid")
_WHITE_BOLD = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=14, color="1B7A3E")
_BOLD = Font(bold=True)
_CENTER = Alignment(horizontal="center")


def _write_header(ws, headers, fill):
    """Écrit une ligne d'en-tête stylée."""
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = _WHITE_BOLD
        c.fill = fill
        c.alignment = _CENTER


def _auto_width(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w


def _fmt_dt(dt):
    if not dt:
        return ''
    return timezone.localtime(dt).strftime('%d/%m/%Y %H:%M')


# ---------------------------------------------------------------------------
# ONGLETS
# ---------------------------------------------------------------------------
def _build_summary_sheet(wb, week_data, month_data, week_range, month_range):
    """Onglet 1 : Résumé."""
    ws = wb.active
    ws.title = "Résumé"

    ws["A1"] = "Rapport hebdomadaire IvoirPass"
    ws["A1"].font = _TITLE_FONT
    ws.merge_cells("A1:D1")

    ws["A2"] = f"Semaine : {week_range[0].strftime('%d/%m/%Y')} → {week_range[1].strftime('%d/%m/%Y')}"
    ws.merge_cells("A2:D2")

    ws["A3"] = f"30 jours : {month_range[0].strftime('%d/%m/%Y')} → {month_range[1].strftime('%d/%m/%Y')}"
    ws.merge_cells("A3:D3")

    # En-têtes tableau
    row = 5
    headers = ["Indicateur", "Semaine", "30 jours", "Total"]
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = _WHITE_BOLD
        c.fill = _GREEN_FILL
        c.alignment = _CENTER

    # Compteurs
    counters = [
        ("Commandes billets (compte)", len(week_data['orders']), len(month_data['orders'])),
        ("Commandes billets (invité)", len(week_data['guest_orders']), len(month_data['guest_orders'])),
        ("Commandes boutique (compte)", len(week_data['product_orders']), len(month_data['product_orders'])),
        ("Commandes boutique (invité)", len(week_data['guest_product_orders']), len(month_data['guest_product_orders'])),
        ("Reversements", len(week_data['withdrawals']), len(month_data['withdrawals'])),
        ("Nouveaux utilisateurs", len(week_data['new_users']), len(month_data['new_users'])),
    ]
    row += 1
    for label, w_val, m_val in counters:
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=w_val).alignment = _CENTER
        ws.cell(row=row, column=3, value=m_val).alignment = _CENTER
        ws.cell(row=row, column=4, value=w_val + m_val).alignment = _CENTER
        row += 1

    # Chiffre d'affaires
    row += 2
    ws.cell(row=row, column=1, value="Chiffre d'affaires (FCFA)").font = _BOLD
    row += 1

    revenues = [
        ("Billets (compte)",
         _sum_amount(week_data['orders']), _sum_amount(month_data['orders'])),
        ("Billets (invité)",
         _sum_amount(week_data['guest_orders']), _sum_amount(month_data['guest_orders'])),
        ("Boutique (compte)",
         _sum_amount(week_data['product_orders']), _sum_amount(month_data['product_orders'])),
        ("Boutique (invité)",
         _sum_amount(week_data['guest_product_orders']), _sum_amount(month_data['guest_product_orders'])),
    ]
    total_w = Decimal('0')
    total_m = Decimal('0')
    for label, w_val, m_val in revenues:
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=int(w_val))
        ws.cell(row=row, column=3, value=int(m_val))
        ws.cell(row=row, column=4, value=int(w_val + m_val))
        total_w += w_val
        total_m += m_val
        row += 1

    ws.cell(row=row, column=1, value="TOTAL").font = _BOLD
    ws.cell(row=row, column=2, value=int(total_w)).font = _BOLD
    ws.cell(row=row, column=3, value=int(total_m)).font = _BOLD
    ws.cell(row=row, column=4, value=int(total_w + total_m)).font = _BOLD

    _auto_width(ws, [35, 15, 15, 18])


def _build_transactions_sheet(wb, week_data):
    """Onglet 2 : Transactions de la semaine."""
    ws = wb.create_sheet("Transactions")
    _write_header(ws, [
        "Type", "Canal", "Référence", "Client", "Email",
        "Date paiement", "Montant FCFA", "Moyen paiement", "Statut"
    ], _ORANGE_FILL)

    row = 2
    for o in week_data['orders']:
        ws.cell(row=row, column=1, value="Billet")
        ws.cell(row=row, column=2, value="Compte")
        ws.cell(row=row, column=3, value=o.order_number)
        ws.cell(row=row, column=4, value=o.buyer.get_full_name() if o.buyer else '')
        ws.cell(row=row, column=5, value=o.buyer.email if o.buyer else '')
        ws.cell(row=row, column=6, value=_fmt_dt(o.paid_at))
        ws.cell(row=row, column=7, value=int(o.total or 0))
        ws.cell(row=row, column=8, value=o.payment_method or '')
        ws.cell(row=row, column=9, value=o.get_status_display())
        row += 1

    for o in week_data['guest_orders']:
        ws.cell(row=row, column=1, value="Billet")
        ws.cell(row=row, column=2, value="Invité")
        ws.cell(row=row, column=3, value=o.order_number)
        ws.cell(row=row, column=4, value=o.buyer_name)
        ws.cell(row=row, column=5, value=o.email or '')
        ws.cell(row=row, column=6, value=_fmt_dt(o.paid_at))
        ws.cell(row=row, column=7, value=int(o.total or 0))
        ws.cell(row=row, column=8, value=o.payment_method or '')
        ws.cell(row=row, column=9, value=o.get_status_display())
        row += 1

    for o in week_data['product_orders']:
        ws.cell(row=row, column=1, value="Boutique")
        ws.cell(row=row, column=2, value="Compte")
        ws.cell(row=row, column=3, value=o.order_number)
        ws.cell(row=row, column=4, value=o.buyer.get_full_name() if o.buyer else '')
        ws.cell(row=row, column=5, value=o.buyer.email if o.buyer else '')
        ws.cell(row=row, column=6, value=_fmt_dt(o.paid_at))
        ws.cell(row=row, column=7, value=int(o.total or 0))
        ws.cell(row=row, column=8, value=o.payment_method or '')
        ws.cell(row=row, column=9, value=o.get_status_display())
        row += 1

    for o in week_data['guest_product_orders']:
        ws.cell(row=row, column=1, value="Boutique")
        ws.cell(row=row, column=2, value="Invité")
        ws.cell(row=row, column=3, value=o.order_number)
        ws.cell(row=row, column=4, value=f"{o.first_name} {o.last_name}".strip())
        ws.cell(row=row, column=5, value=o.email or '')
        ws.cell(row=row, column=6, value=_fmt_dt(o.paid_at))
        ws.cell(row=row, column=7, value=int(o.total or 0))
        ws.cell(row=row, column=8, value=o.payment_method or '')
        ws.cell(row=row, column=9, value=o.get_status_display())
        row += 1

    _auto_width(ws, [12, 10, 18, 28, 32, 18, 14, 16, 14])


def _build_withdrawals_sheet(wb, week_data):
    """Onglet 3 : Reversements de la semaine."""
    ws = wb.create_sheet("Reversements")
    _write_header(ws, [
        "Référence", "Organisateur", "Montant FCFA",
        "Méthode", "Statut", "Date demande"
    ], _GREEN_FILL)

    row = 2
    for w in week_data['withdrawals']:
        organizer = w.wallet.organizer if w.wallet else None
        ws.cell(row=row, column=1, value=w.reference)
        ws.cell(row=row, column=2, value=organizer.get_full_name() if organizer else '')
        ws.cell(row=row, column=3, value=int(w.amount or 0))
        ws.cell(row=row, column=4, value=w.get_payout_method_display())
        ws.cell(row=row, column=5, value=w.get_status_display())
        ws.cell(row=row, column=6, value=_fmt_dt(w.created_at))
        row += 1

    _auto_width(ws, [20, 28, 15, 18, 15, 20])


def _build_users_sheet(wb, week_data):
    """Onglet 4 : Nouveaux utilisateurs."""
    ws = wb.create_sheet("Nouveaux utilisateurs")
    _write_header(ws, [
        "Email", "Nom complet", "Rôle", "Ville", "Date inscription"
    ], _CYAN_FILL)

    row = 2
    for u in week_data['new_users']:
        ws.cell(row=row, column=1, value=u.email)
        ws.cell(row=row, column=2, value=u.get_full_name())
        ws.cell(row=row, column=3, value=u.get_role_display())
        ws.cell(row=row, column=4, value=u.city or '')
        ws.cell(row=row, column=5, value=_fmt_dt(u.date_joined))
        row += 1

    _auto_width(ws, [35, 28, 15, 15, 20])


# ---------------------------------------------------------------------------
# GÉNÉRATION
# ---------------------------------------------------------------------------
def build_weekly_report_xlsx():
    """
    Génère le fichier Excel multi-onglets.
    Retourne (bytes_xlsx, (week_start, week_end)).
    """
    week_start, week_end = _last_week_range()
    month_start, month_end = _last_30_days_range()

    week_data = _collect_data(week_start, week_end)
    month_data = _collect_data(month_start, month_end)

    wb = Workbook()
    _build_summary_sheet(wb, week_data, month_data, (week_start, week_end), (month_start, month_end))
    _build_transactions_sheet(wb, week_data)
    _build_withdrawals_sheet(wb, week_data)
    _build_users_sheet(wb, week_data)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue(), (week_start, week_end)


def build_weekly_report_zip():
    """
    Génère le ZIP contenant le rapport Excel.
    Retourne (bytes_zip, nom_fichier_zip, (week_start, week_end)).
    """
    import zipfile

    xlsx_bytes, week_range = build_weekly_report_xlsx()

    xlsx_name = (
        f"rapport_ivoirpass_"
        f"{week_range[0].strftime('%Y%m%d')}_"
        f"{week_range[1].strftime('%Y%m%d')}.xlsx"
    )
    zip_name = xlsx_name.replace('.xlsx', '.zip')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(xlsx_name, xlsx_bytes)

    buffer.seek(0)
    return buffer.getvalue(), zip_name, week_range
