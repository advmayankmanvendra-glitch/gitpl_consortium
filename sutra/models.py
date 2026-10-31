"""Model backends.

All backends share one interface::

    model.complete(system, messages, tools=None, schema=None) -> Response

``messages`` use the Anthropic Messages API shape (``role`` plus ``content``
that is a string or a list of content blocks), which is also what the agent
loop builds. ``schema`` is the JSON Schema expected for structured output; a
backend may ignore it (the interpreter validates the reply either way).
"""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .errors import ModelError

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Response:
    text: str
    tool_calls: list = field(default_factory=list)
    content: list = field(default_factory=list)  # assistant blocks to append to history


def text_of(content):
    """Extract plain text from message content (a string or a list of blocks)."""
    if isinstance(content, str):
        return content
    pieces = []
    for block in content:
        if block.get("type") == "text":
            pieces.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            pieces.append(str(block.get("content", "")))
    return "\n".join(pieces)


class Model:
    name = "model"

    def complete(self, system, messages, tools=None, schema=None):
        raise NotImplementedError

    def __repr__(self):
        return f"<model {self.name}>"


class MockModel(Model):
    """Offline, deterministic model for tests and demos.

    With no script, it echoes the last user message for plain asks and
    returns a placeholder value matching the schema for typed asks.

    With a script (a list), each call returns the next item. A string item is
    a text reply; a map with a ``tool`` key is a tool call, e.g.
    ``{tool: "search", args: {query: "x"}}``; any other value is sent as JSON.
    """

    def __init__(self, script=None):
        self.script = list(script) if script is not None else None
        self.calls = []
        self.name = "mock"
        self._next_id = 0

    def complete(self, system, messages, tools=None, schema=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools, "schema": schema})
        if self.script is not None:
            if not self.script:
                raise ModelError("mock model ran out of scripted replies")
            item = self.script.pop(0)
            if isinstance(item, dict) and "tool" in item:
                self._next_id += 1
                call = ToolCall(f"call_{self._next_id}", item["tool"], dict(item.get("args") or {}))
                block = {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
                return Response("", [call], [block])
            text = item if isinstance(item, str) else json.dumps(item)
            return Response(text, [], [{"type": "text", "text": text}])
        if schema is not None:
            text = json.dumps(example_from_schema(schema))
        else:
            last = text_of(messages[-1]["content"]) if messages else ""
            text = f"[mock reply to: {last.strip()}]"
        return Response(text, [], [{"type": "text", "text": text}])


def example_from_schema(schema):
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "string":
        return "example"
    if kind == "number":
        return 0
    if kind == "boolean":
        return False
    if kind == "array":
        return [example_from_schema(schema.get("items", {}))]
    if kind == "object":
        return {k: example_from_schema(v) for k, v in schema.get("properties", {}).items()}
    return "example"


class AnthropicModel(Model):
    """Claude via the Anthropic Messages API, using only the standard library."""

    def __init__(self, model=DEFAULT_ANTHROPIC_MODEL, max_tokens=1024, temperature=None, api_key=None):
        self.model = model
        self.name = f"anthropic:{model}"
        self.max_tokens = int(max_tokens)
        self.temperature = temperature
        self.api_key = api_key

    def complete(self, system, messages, tools=None, schema=None):
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ModelError(
                "ANTHROPIC_API_KEY is not set",
                hint='export ANTHROPIC_API_KEY=..., or run offline with: use "mock"',
            )
        body = {"model": self.model, "max_tokens": self.max_tokens, "messages": messages}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools
        if self.temperature is not None:
            body["temperature"] = self.temperature
        request = urllib.request.Request(
            os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
            hints = {
                401: "check that ANTHROPIC_API_KEY is valid",
                404: f"check the model name '{self.model}'",
                429: "you are being rate limited; wait a moment and try again",
                529: "the API is overloaded; try again shortly",
            }
            raise ModelError(f"Anthropic API error {exc.code}: {detail}", hint=hints.get(exc.code)) from None
        except urllib.error.URLError as exc:
            raise ModelError(
                f"could not reach the Anthropic API: {exc.reason}", hint="check your network connection"
            ) from None

        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in blocks if b.get("type") == "tool_use"]
        return Response(text, calls, blocks)


def make_model(spec, options=None):
    """Build a model from a spec string such as ``"mock"`` or ``"anthropic:claude-opus-5-5"``."""
    options = dict(options or {})
    if isinstance(spec, Model):
        return spec
    if not isinstance(spec, str):
        raise ModelError(f"model spec must be a string, got {type(spec).__name__}")
    provider, _, name = spec.partition(":")
    if provider == "mock":
        return MockModel(options.get("script"))
    if provider in ("anthropic", "claude"):
        return AnthropicModel(name or DEFAULT_ANTHROPIC_MODEL, **_anthropic_options(options))
    if spec.startswith("claude-"):
        return AnthropicModel(spec, **_anthropic_options(options))
    raise ModelError(f"unknown model '{spec}'", hint=f'try "mock" or "anthropic:{DEFAULT_ANTHROPIC_MODEL}"')


def _anthropic_options(options):
    allowed = {"max_tokens", "temperature", "api_key"}
    unknown = set(options) - allowed
    if unknown:
        raise ModelError(f"unknown model option(s): {', '.join(sorted(unknown))}")
    return options
