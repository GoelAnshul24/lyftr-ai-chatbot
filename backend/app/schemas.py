from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: str | None = None

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, v):
        # Strip first; length limits are then checked on the stripped text.
        return v.strip() if isinstance(v, str) else v
