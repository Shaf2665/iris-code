from typing import Iterator
from openai import OpenAI

from .config import Config

_EXTRACT_PROMPT = (
    "Extract the key fact to remember from the developer's message as a single short note "
    "(max 15 words, no filler). Reply with only the fact, nothing else. "
    "Prefer durable coding context: language/stack preferences, tools, conventions, "
    "project facts. If the message states no fact worth remembering (e.g. a question or "
    "small talk), reply with exactly: NONE"
)


class LLMClient:
    def __init__(self, config: Config):
        self._client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self._model = config.model

    def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        accumulated_tool_calls: list,
    ) -> "Iterator[str]":
        kwargs = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 2048,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
        response = self._client.chat.completions.create(**kwargs)
        tc_builders: dict[int, dict] = {}

        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                yield delta.content

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tc_builders:
                        tc_builders[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tc_builders[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tc_builders[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            tc_builders[idx]["arguments"] += tc.function.arguments

        for idx in sorted(tc_builders.keys()):
            accumulated_tool_calls.append(tc_builders[idx])

    def extract(self, user_message: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _EXTRACT_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=200,  # headroom so reasoning models still emit a visible answer
            stream=False,
        )
        content = response.choices[0].message.content
        return content.strip() if content else ""
