/* ═══════════════════════════════════════════════════════
   Widget Chatbot IvoirPass — Logique Alpine.js
   ═══════════════════════════════════════════════════════ */

document.addEventListener('alpine:init', () => {
  Alpine.data('chatbotWidget', () => ({
    open: false,
    loading: false,
    draft: '',
    messages: [],
    suggestWhatsapp: false,
    whatsappUrl: '',
    sessionKey: '',
    hasUnread: false,

    init() {
      // Récupérer ou créer la session
      let key = localStorage.getItem('ivoirpass_chat_session');
      if (!key) {
        key = this.generateUuid();
        localStorage.setItem('ivoirpass_chat_session', key);
      }
      this.sessionKey = key;

      // URL WhatsApp (récupérée côté serveur au premier message)
      this.whatsappUrl = 'https://wa.me/2250702063876'; // fallback

      // Restaurer l'historique visuel depuis la sessionStorage (optionnel)
      const saved = sessionStorage.getItem('ivoirpass_chat_messages');
      if (saved) {
        try {
          this.messages = JSON.parse(saved);
        } catch (e) {
          this.messages = [];
        }
      }

      // Scroll auto à chaque nouveau message
      this.$watch('messages', () => {
        this.$nextTick(() => this.scrollToBottom());
      });
    },

    // ----------------------------------------------------------------
    // Getters
    // ----------------------------------------------------------------

    // URL vers la page de réclamation, avec le session_key
    // pour pré-remplir l'historique de conversation côté serveur.
    get disputeUrl() {
      return '/reclamation/?source=chatbot&session=' + encodeURIComponent(this.sessionKey);
    },

    // ----------------------------------------------------------------
    // Utilitaires
    // ----------------------------------------------------------------
    generateUuid() {
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      });
    },

    scrollToBottom() {
      const el = this.$refs.messages;
      if (el) el.scrollTop = el.scrollHeight;
    },

    persistMessages() {
      // On ne garde que les 20 derniers messages pour ne pas exploser la sessionStorage
      const trimmed = this.messages.slice(-20);
      sessionStorage.setItem('ivoirpass_chat_messages', JSON.stringify(trimmed));
    },

    // ----------------------------------------------------------------
    // Envoyer un message
    // ----------------------------------------------------------------
    async send() {
      const text = this.draft.trim();
      if (!text || this.loading) return;

      // Ajouter le message utilisateur
      this.messages.push({ role: 'user', content: text });
      this.draft = '';
      this.loading = true;
      this.persistMessages();
      this.scrollToBottom();

      try {
        const response = await fetch('/api/chat/message/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': this.getCsrfToken(),
          },
          body: JSON.stringify({
            message: text,
            session_key: this.sessionKey,
          }),
        });

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.error || `Erreur ${response.status}`);
        }

        const data = await response.json();

        // Ajouter la réponse du bot
        this.messages.push({ role: 'assistant', content: data.answer });
        this.suggestWhatsapp = !!data.suggest_whatsapp;
        if (data.whatsapp_url) this.whatsappUrl = data.whatsapp_url;

        // Si le panneau est fermé, afficher un badge
        if (!this.open) this.hasUnread = true;

      } catch (err) {
        this.messages.push({
          role: 'assistant',
          content:
            "Désolé, une erreur technique est survenue. " +
            "Réessayez dans quelques instants ou ouvrez une réclamation.",
        });
        this.suggestWhatsapp = true;
      } finally {
        this.loading = false;
        this.persistMessages();
        this.scrollToBottom();
      }
    },

    // ----------------------------------------------------------------
    // Reset conversation
    // ----------------------------------------------------------------
    reset() {
      if (!confirm('Démarrer une nouvelle conversation ? L\'historique actuel sera effacé.')) {
        return;
      }
      this.messages = [];
      this.suggestWhatsapp = false;
      // Nouvelle session (nouvel ID pour repartir de zéro côté serveur)
      const newKey = this.generateUuid();
      localStorage.setItem('ivoirpass_chat_session', newKey);
      this.sessionKey = newKey;
      sessionStorage.removeItem('ivoirpass_chat_messages');
    },

    // ----------------------------------------------------------------
    // CSRF token (depuis les cookies Django)
    // ----------------------------------------------------------------
    getCsrfToken() {
      const name = 'csrftoken';
      const cookies = document.cookie.split(';');
      for (let c of cookies) {
        c = c.trim();
        if (c.startsWith(name + '=')) {
          return decodeURIComponent(c.substring(name.length + 1));
        }
      }
      return '';
    },
  }));
});