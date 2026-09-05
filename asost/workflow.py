"""Resumable, checkpointed book workflow."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from threading import Event
from .providers import CancelledError

TERMINAL = {"completed", "failed", "cancelled"}


class BookWorkflow:
    def __init__(self, tool, memory, *, workflow_id="book"):
        self.tool, self.memory, self.workflow_id = tool, memory, workflow_id

    def run(self, manifest_path, cancel_event: Event | None = None):
        cancel_event = cancel_event or Event()
        manifest_path = Path(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        state = self.memory.read(self.workflow_id, {"status": "pending", "pages": {}, "provenance": []})
        state["status"] = "running"
        self.memory.write(self.workflow_id, state)
        try:
            for page in manifest["pages"]:
                page_id = str(page["number"])
                if state["pages"].get(page_id, {}).get("status") == "completed":
                    continue
                if cancel_event.is_set():
                    raise CancelledError("operation cancelled")
                text = (manifest_path.parent / page["text"]).read_text(encoding="utf-8")
                translated = self.tool.translate(text, manifest.get("context", ""), cancel_event)
                state["pages"][page_id] = {"status": "completed", "translation": translated}
                state["provenance"].append({
                    "page": int(page_id), "provider": self.tool.provider.name,
                    "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "assets": list(page.get("images", [])),
                })
                self.memory.write(self.workflow_id, state)
            state["status"] = "completed"
        except CancelledError:
            state["status"] = "cancelled"
            self.memory.write(self.workflow_id, state)
            raise
        except Exception:
            state["status"] = "failed"
            self.memory.write(self.workflow_id, state)
            raise
        self.memory.write(self.workflow_id, state)
        return state
