"""
Tests de la page publique de suivi de litige (ajout 2026-10-15).
"""
import uuid

from django.test import TestCase
from django.urls import reverse

from apps.dashboard.models import Dispute, DisputeMessage


class DisputePublicTests(TestCase):
    """Teste /reclamation/<token>/ et sa réponse."""

    def setUp(self):
        self.dispute = Dispute.objects.create(
            type=Dispute.Type.QUESTION,
            subject='Question test',
            description='Description test',
            email='client@test.com',
        )

    def test_public_detail_accessible_with_token(self):
        """Le client accède à son ticket via son access_token."""
        url = reverse('dispute_detail', kwargs={'access_token': self.dispute.access_token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.dispute.reference)
        self.assertContains(response, 'Question test')

    def test_public_detail_404_with_wrong_token(self):
        """Un token inconnu → 404."""
        fake = uuid.uuid4()
        url = reverse('dispute_detail', kwargs={'access_token': fake})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_public_reply_creates_message(self):
        """Le client peut répondre → crée un DisputeMessage."""
        url = reverse('dispute_reply', kwargs={'access_token': self.dispute.access_token})
        response = self.client.post(url, {'content': 'Ma réponse'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.messages.count(), 1)
        msg = self.dispute.messages.first()
        self.assertEqual(msg.content, 'Ma réponse')
        self.assertIsNone(msg.author)
        self.assertFalse(msg.is_internal)

    def test_public_reply_blocks_when_closed(self):
        """Réclamation fermée → impossible de répondre."""
        self.dispute.status = Dispute.Status.CLOSED
        self.dispute.save()
        url = reverse('dispute_reply', kwargs={'access_token': self.dispute.access_token})
        response = self.client.post(url, {'content': 'Trop tard'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.dispute.messages.count(), 0)

    def test_public_reply_blocks_empty_message(self):
        """Message vide → refusé."""
        url = reverse('dispute_reply', kwargs={'access_token': self.dispute.access_token})
        self.client.post(url, {'content': '   '})
        self.assertEqual(self.dispute.messages.count(), 0)

    def test_internal_notes_hidden_from_thread(self):
        """Les notes internes ne s'affichent pas dans le fil client."""
        DisputeMessage.objects.create(
            dispute=self.dispute,
            author_email='support@mks.com',
            content='Note interne visible uniquement admin',
            is_internal=True,
        )
        DisputeMessage.objects.create(
            dispute=self.dispute,
            author_email='client@test.com',
            content='Message public',
            is_internal=False,
        )
        url = reverse('dispute_detail', kwargs={'access_token': self.dispute.access_token})
        response = self.client.get(url)
        self.assertNotContains(response, 'Note interne visible')
        self.assertContains(response, 'Message public')
