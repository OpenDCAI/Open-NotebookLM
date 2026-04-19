from __future__ import annotations


def ensure_langgraph_compat() -> None:
    """Patch old langchain-core installs so current langgraph can import."""
    import langchain_core.messages as messages_module

    if hasattr(messages_module, "RemoveMessage"):
        return

    from langchain_core.messages import BaseMessage

    class RemoveMessage(BaseMessage):
        type: str = "remove"

        def __init__(self, content: str = "", **kwargs):
            super().__init__(content=content, **kwargs)

    messages_module.RemoveMessage = RemoveMessage

