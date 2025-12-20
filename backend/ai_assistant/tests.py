from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock

User = get_user_model()


class AIAssistantTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpassword123"
        )
        self.client.force_authenticate(user=self.user)
        self.chat_url = reverse("ai_chat")

    @patch("ai_assistant.views.OpenAI")
    def test_chat_with_clipboard_text(self, mock_openai):
        """Test chat with text content"""
        # Mock OpenAI response
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock non-stream response
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "AI response"
        mock_response.choices = [mock_choice]

        mock_client.chat.completions.create.return_value = mock_response

        data = {
            "type": "text",
            "content": "Hello world",
            "user_quest": "Translate to Spanish",
            "stream": "false",  # Disable stream for simple testing
        }

        response = self.client.post(self.chat_url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["reply"], "AI response")

    @patch("ai_assistant.views.OpenAI")
    def test_chat_stream(self, mock_openai):
        """Test chat with stream enabled"""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock stream response generator
        def stream_generator():
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock(delta=MagicMock(content="Hello"))]
            yield chunk1
            chunk2 = MagicMock()
            chunk2.choices = [MagicMock(delta=MagicMock(content=" World"))]
            yield chunk2

        mock_client.chat.completions.create.return_value = stream_generator()

        data = {
            "type": "text",
            "content": "Hi",
            "user_quest": "Say hi",
            "stream": "true",
        }

        response = self.client.post(self.chat_url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.streaming)

        # Consume stream
        content = b"".join(response.streaming_content)
        self.assertIn(b'data: {"type": "delta", "content": "Hello"}\n\n', content)
        self.assertIn(b'data: {"type": "delta", "content": " World"}\n\n', content)
        self.assertIn(b"data: [DONE]\n\n", content)

    @patch("ai_assistant.views.OpenAI")
    def test_chat_error(self, mock_openai):
        """Test chat error handling"""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        data = {
            "type": "text",
            "content": "Hi",
            "user_quest": "Error test",
            "stream": "false",
        }

        response = self.client.post(self.chat_url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
