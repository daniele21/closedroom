from __future__ import annotations

import io
import json


class RuntimeStub:
    def __init__(self):
        self.release_calls = 0

    def ensure_llm_ready(self, **kwargs):
        return {"base_url": "http://127.0.0.1:1235", "model": "qwen3-vl-4b"}

    def release_llm_residency(self):
        self.release_calls += 1
        return {"released": True, "cold": True}


class TaskAwareClientStub:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        task = messages[0]["task"]
        self.calls.append(task)
        payloads = {
            "meeting_ui": {
                "platform": "meet", "layout": "gallery", "participants": [],
                "active_speakers": [], "evidence": [], "confidence": 0.9,
            },
            "meeting_state": {
                "platform": "meet", "layout": "gallery", "visible_participant_count": 2,
                "screen_share": {"active": False, "presenter": None},
                "visible_activity": [], "confidence": 0.9,
            },
            "shared_content": {
                "content_type": "slide", "title": None, "visible_text": [],
                "key_information": [], "content_state": "stable", "confidence": 0.9,
            },
        }
        return json.dumps(payloads[task])


class LegacyClientStub:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return json.dumps({
            "platform": "google_meet", "layout": "gallery",
            "participants": ["Salvo", "Andrea"], "active_speakers": ["Salvo"],
            "evidence": ["highlighted_tile", "visible_name"], "confidence": 0.95,
        })


class SequencedClientStub:
    def __init__(self, responses):
        self.responses = iter(responses)

    def chat(self, messages, **kwargs):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class InvalidMeetingStateClientStub(TaskAwareClientStub):
    def chat(self, messages, **kwargs):
        if messages[0]["task"] == "meeting_state":
            self.calls.append("meeting_state")
            return json.dumps({
                "platform": "meet", "layout": "gallery", "visible_participant_count": 2,
                "screen_share": {"active": "false", "presenter": None},
                "visible_activity": [], "confidence": 0.9,
            })
        return super().chat(messages, **kwargs)


def jpeg(color: str = "blue") -> bytes:
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (120, 80), color=color).save(output, format="JPEG")
    return output.getvalue()
