from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from local_asr_server.llm import NemotronLocalProvider, VoxtralLocalProvider
from local_asr_server.visual_intelligence.service import PostMeetingVisualService, VISUAL_PROMPT


class LocalAIRuntimePortTests(unittest.TestCase):
    def test_text_provider_uses_injected_local_ai_port(self) -> None:
        client = Mock()
        client.is_ready.return_value = True
        client.analyze_text.return_value = {"summary": "ok"}
        port = Mock()
        port.create_client.return_value = client
        provider = NemotronLocalProvider(
            base_url="http://127.0.0.1:1235",
            model="model-a",
            local_ai=port,
        )

        result = provider.analyze("hello")

        self.assertEqual(result, {"summary": "ok"})
        port.create_client.assert_called_once_with(
            base_url="http://127.0.0.1:1235",
            model="model-a",
        )
        client.analyze_text.assert_called_once_with("hello", language="it")

    def test_audio_provider_uses_injected_local_ai_port(self) -> None:
        client = Mock()
        client.is_ready.return_value = True
        client.analyze_audio.return_value = {"summary": "audio"}
        port = Mock()
        port.create_client.return_value = client
        provider = VoxtralLocalProvider(
            base_url="http://127.0.0.1:1235",
            model="model-b",
            local_ai=port,
        )

        result = provider.analyze_audio("meeting.wav", task="insights")

        self.assertEqual(result, {"summary": "audio"})
        port.create_client.assert_called_once_with(
            base_url="http://127.0.0.1:1235",
            model="model-b",
        )
        client.analyze_audio.assert_called_once_with(
            audio_path="meeting.wav",
            task="insights",
            question=None,
            language="it",
        )

    def test_visual_service_uses_same_port_for_client_and_image_message(self) -> None:
        client = Mock()
        port = Mock()
        port.create_client.return_value = client
        port.prepare_image_message.return_value = [{"role": "user"}]
        service = PostMeetingVisualService(local_ai=port)

        self.assertIs(service._client("http://127.0.0.1:1235", "vision-model"), client)
        self.assertEqual(
            service._image_message(Path("frame.jpg")),
            [{"role": "user"}],
        )
        port.create_client.assert_called_once_with(
            base_url="http://127.0.0.1:1235",
            model="vision-model",
        )
        port.prepare_image_message.assert_called_once_with(Path("frame.jpg"), VISUAL_PROMPT)

    def test_application_workflows_do_not_import_local_llm_server_directly(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative in (
            "src/local_asr_server/llm.py",
            "src/local_asr_server/visual_intelligence/service.py",
        ):
            source = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn("from local_llm_server", source)
            self.assertNotIn("import local_llm_server", source)


if __name__ == "__main__":
    unittest.main()
