"""Small dispatch boundary used by Hermes without coupling tests to its runtime."""
class ASOSTHermesDispatcher:
    def __init__(self, workflow):
        self.workflow = workflow

    def dispatch(self, command, **payload):
        if command != "translate_book":
            raise ValueError(f"unsupported ASOST command: {command}")
        return self.workflow.run(payload["manifest"], payload.get("cancel_event"))
