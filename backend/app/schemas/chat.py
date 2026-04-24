from typing import Literal

from pydantic import BaseModel


class StartThreadRequest(BaseModel):
    mode: Literal["companion", "knowledge", "test", "crisis"] = "companion"
    title: str | None = None


class SendMessageRequest(BaseModel):
    user_id: str
    content: str
    input_type: Literal["text", "voice", "test", "system"] = "text"
    user_mode: Literal["teen", "adult"] = "adult"
