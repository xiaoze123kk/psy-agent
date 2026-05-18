from __future__ import annotations

from time import monotonic


ChatStreamEvent = tuple[str, dict[str, object]]


def iter_stream_chunks(text: str, *, chunk_size: int = 6):
    buffer = ""
    stop_chars = set("。！？!?；;\n")
    for char in text:
        buffer += char
        if len(buffer) >= chunk_size or char in stop_chars:
            yield buffer
            buffer = ""

    if buffer:
        yield buffer


def graph_update_event(node: str, **data: object) -> ChatStreamEvent:
    return "graph_update", {"node": node, "status": "completed", **data}


def heartbeat_event(started_at: float) -> ChatStreamEvent:
    return "heartbeat", {"status": "running", "elapsed_ms": int((monotonic() - started_at) * 1000)}
