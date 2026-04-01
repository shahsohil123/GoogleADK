"""
OpenAI-compatible adapter server for functionGemma-270m.

Bridges functionGemma's custom tool format:
  <start_function_call>call:tool{param:<escape>val<escape>}<end_function_call>

...to OpenAI-style tool_calls that ADK/LiteLLM understand:
  {"tool_calls": [{"function": {"name": "...", "arguments": "..."}}]}

Run with:
  python functiongemma_server.py
  # Listens on http://localhost:11435

Configure ADK to use it:
  model="openai/functiongemma"
  OPENAI_API_BASE=http://localhost:11435/v1
  OPENAI_API_KEY=none
"""

import json
import re
import time
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoProcessor

# ── Model loading ────────────────────────────────────────────────────────────
MODEL_ID = "unsloth/functiongemma-270m-it"
print(f"Loading {MODEL_ID} …")
processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype="auto", device_map="auto")
print("Model ready.\n")

app = FastAPI(title="functionGemma OpenAI Adapter")


# ── Request / response schemas ───────────────────────────────────────────────
class Message(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class Tool(BaseModel):
    type: str
    function: dict


class ChatRequest(BaseModel):
    model: str = "functiongemma"
    messages: list[Message]
    tools: Optional[list[Tool]] = None
    max_tokens: Optional[int] = 256
    temperature: Optional[float] = 0.1
    stream: Optional[bool] = False


# ── Format conversion ────────────────────────────────────────────────────────
def openai_messages_to_functiongemma(messages: list[Message], tools: list[Tool]) -> list[dict]:
    """Convert OpenAI-style messages to functionGemma chat template format."""
    result = [
        {
            "role": "developer",
            "content": "You are a helpful assistant. Use the provided tools to answer the user's request."
        }
    ]
    for msg in messages:
        if msg.role == "system":
            result[0]["content"] = msg.content
        elif msg.role == "user":
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == "assistant":
            if msg.tool_calls:
                # Convert tool_call back to functiongemma format for multi-turn
                tc = msg.tool_calls[0]
                fn = tc.get("function", {})
                args = json.loads(fn.get("arguments", "{}"))
                args_str = ", ".join(
                    f"{k}:<escape>{v}<escape>" for k, v in args.items()
                )
                content = f"<start_function_call>call:{fn['name']}{{{args_str}}}<end_function_call>"
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": "assistant", "content": msg.content or ""})
        elif msg.role == "tool":
            result.append({
                "role": "tool",
                "content": msg.content or "",
                "tool_call_id": msg.tool_call_id,
            })
    return result


FUNC_CALL_RE = re.compile(
    r"<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>",
    re.DOTALL,
)
PARAM_RE = re.compile(r"(\w+):<escape>(.*?)<escape>")


def parse_functiongemma_output(text: str):
    """
    Parse functionGemma output into (tool_name, arguments_dict) or None.
    Returns None if the response is plain text (no tool call).
    """
    match = FUNC_CALL_RE.search(text)
    if not match:
        return None, text.strip()

    tool_name = match.group(1)
    params_str = match.group(2)
    arguments = {m.group(1): m.group(2) for m in PARAM_RE.finditer(params_str)}
    return tool_name, arguments


def build_openai_response(text: str, model_name: str) -> dict:
    """Convert functionGemma output to OpenAI chat completion response."""
    tool_name, payload = parse_functiongemma_output(text)
    call_id = f"call_{uuid.uuid4().hex[:8]}"

    if tool_name:
        # Tool call response
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(payload),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    else:
        # Plain text response
        message = {"role": "assistant", "content": payload}
        finish_reason = "stop"

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": len(text.split()),
            "total_tokens": len(text.split()),
        },
    }


# ── API endpoints ────────────────────────────────────────────────────────────
@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": "functiongemma", "object": "model", "created": 0, "owned_by": "google"}]
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    tools = req.tools or []
    tool_schemas = [t.dict() for t in tools] if tools else None

    # Convert to functionGemma format
    fg_messages = openai_messages_to_functiongemma(req.messages, tools)

    # Tokenize
    inputs = processor.apply_chat_template(
        fg_messages,
        tools=tool_schemas,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )

    # Generate
    out = model.generate(
        **inputs.to(model.device),
        pad_token_id=processor.eos_token_id,
        max_new_tokens=req.max_tokens or 256,
        do_sample=False,
    )

    raw = processor.decode(
        out[0][len(inputs["input_ids"][0]):],
        skip_special_tokens=True
    )
    print(f"[functionGemma raw] {raw!r}")

    response = build_openai_response(raw, req.model)
    return JSONResponse(content=response)


if __name__ == "__main__":
    print("Starting functionGemma OpenAI adapter on http://localhost:11435")
    uvicorn.run(app, host="0.0.0.0", port=11435, log_level="warning")
