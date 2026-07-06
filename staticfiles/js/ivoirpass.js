/* ============================================
   IVOIRPASS V2 — Scripts globaux
   ============================================ */

document.addEventListener('DOMContentLoaded', function () {

  // --- Auto-dismiss des alertes après 5 secondes ---
  document.querySelectorAll('.ip-alert[data-auto-dismiss]').forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 5000);
  });

  // --- Active le lien navbar correspondant à la page courante ---
  const currentPath = window.location.pathname;
  document.querySelectorAll('.ip-navbar .nav-link').forEach(function (link) {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

  // --- Confirmation avant suppression ---
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      const msg = el.dataset.confirm || 'Êtes-vous sûr de vouloir effectuer cette action ?';
      if (!confirm(msg)) e.preventDefault();
    });
  });

  // --- Formatage des montants FCFA ---
  document.querySelectorAll('[data-fcfa]').forEach(function (el) {
    const amount = parseFloat(el.dataset.fcfa);
    if (!isNaN(amount)) {
      el.textContent = new Intl.NumberFormat('fr-FR').format(amount) + ' FCFA';
    }
  });

});

/* --- Utilitaire : formater un montant FCFA --- */
function formatFCFA(amount) {
  return new Intl.NumberFormat('fr-FR').format(amount) + ' FCFA';
}

/* --- Utilitaire : copier du texte dans le presse-papier --- */
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(function () {
    showToast('Copié !', 'success');
  });
}

/* --- Mini toast notification --- */
function showToast(message, type = 'success') {
  const colors = {
    success: '#1B7A3E',
    error:   '#dc3545',
    warning: '#F47920',
    info:    '#0dcaf0',
  };
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; bottom: 24px; right: 24px; z-index: 9999;
    background: ${colors[type] || colors.success}; color: white;
    padding: 12px 24px; border-radius: 8px;
    font-weight: 600; font-size: 0.9rem;
    box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    animation: slideInRight 0.3s ease;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}