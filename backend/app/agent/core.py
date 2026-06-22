from __future__ import annotations

import inspect
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, create_model

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import AgentToolContext, ToolDefinition, execute_tool, list_registered_tools
from app.llm import create_chat_model
from app.schemas.chat import AgentAnalysisResult


class AgentState(BaseModel):
    """Runtime state passed through the hybrid workflow/agent loop."""

    conversation_id: int
    history: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    plan: list[str] = Field(default_factory=list)
    tool_results: dict[str, Any] = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)
    risk_level: str = "L1"


class SteamAnalysisAgent:
    """
    LangChain-backed agent facade with a deterministic fallback.

    The app can still run without an API key or LangChain installed. When the runtime can
    build a DeepSeek model and LangChain tools, this class delegates to `create_agent` so
    the agent can choose read tools autonomously. Otherwise it returns a conservative
    structured response and the deterministic workflow remains available.
    """

    def __init__(
        self,
        llm: Any | None = None,
        tools: list[Any] | None = None,
        session: Any | None = None,
        agent: Any | None = None,
        unavailable_reason: str | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools or []
        self.session = session
        self.agent = agent
        self.unavailable_reason = unavailable_reason

    @classmethod
    def from_context(cls, ctx: AgentToolContext, memory_context: str = "") -> SteamAnalysisAgent:
        llm, reason = _build_llm()
        if llm is None:
            return cls(session=ctx.session, unavailable_reason=reason)

        tools, reason = _build_langchain_tools(ctx)
        if not tools:
            return cls(llm=llm, session=ctx.session, unavailable_reason=reason)

        try:
            from langchain.agents import create_agent
        except Exception as exc:
            return cls(
                llm=llm,
                tools=tools,
                session=ctx.session,
                unavailable_reason=f"LangChain create_agent 不可用：{exc}",
            )

        # Build dynamic system prompt with memory context
        prompt = SYSTEM_PROMPT
        if memory_context:
            prompt += (
                "\n\n## 长期记忆\n"
                "以下是之前对话中积累的信息，可用于理解用户意图：\n"
                f"{memory_context}"
            )

        agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=prompt,
        )
        return cls(llm=llm, tools=tools, session=ctx.session, agent=agent)

    @property
    def is_available(self) -> bool:
        return self.agent is not None

    async def run(self, query: str, state: AgentState) -> AgentAnalysisResult:
        if self.agent is None:
            return AgentAnalysisResult(
                task_type=str(state.context.get("task_type") or "unknown"),
                risk_level=state.risk_level,  # type: ignore[arg-type]
                answer=(
                    "当前没有可用的 DeepSeek/LangChain 运行时，已降级到确定性 Workflow。"
                    f"{self.unavailable_reason or '请确认 API key 与核心依赖已配置。'}"
                ),
                uncertainties=["LLM Agent 未启用，本次回答未执行 ReAct 推理循环。"],
                memory_used=bool(state.history),
            )

        payload = {
            "messages": [
                *_messages_from_history(state.history),
                {"role": "user", "content": query},
            ],
        }

        import time as time_mod

        from app.core.metrics import record_llm_call

        llm_status = "success"
        t0 = time_mod.perf_counter()
        try:
            if hasattr(self.agent, "ainvoke"):
                response = await self.agent.ainvoke(payload)
            else:
                response = self.agent.invoke(payload)
        except Exception:
            llm_status = "error"
            raise
        finally:
            if self.llm:
                model_name = getattr(self.llm, "model_name", None) or getattr(
                    self.llm, "model", "unknown"
                )
            else:
                model_name = "none"
            latency_ms = int((time_mod.perf_counter() - t0) * 1000)
            record_llm_call(str(model_name), llm_status, latency_ms)

        structured = _extract_structured_response(response)
        if structured is not None:
            structured.memory_used = bool(state.history)
            return structured

        return AgentAnalysisResult(
            task_type=str(state.context.get("task_type") or "unknown"),
            risk_level=state.risk_level,  # type: ignore[arg-type]
            answer=_extract_answer(response),
            uncertainties=state.uncertainties,
            memory_used=bool(state.history),
        )


def _build_llm() -> tuple[Any | None, str | None]:
    """Build an LLM chat model using the configured provider.

    Returns (model, None) on success or (None, reason) on failure.
    """
    from app.llm import get_provider_info

    info = get_provider_info()
    if not info.available:
        return None, f"LLM 不可用：{info.reason}"

    llm = create_chat_model(temperature=0.3)
    if llm is None:
        return None, f"无法创建 {info.provider} 模型，请检查 API key 与依赖。"

    return llm, None


def _build_langchain_tools(ctx: AgentToolContext) -> tuple[list[Any], str | None]:
    try:
        from langchain_core.tools import StructuredTool
    except Exception as exc:
        return [], f"请安装 `langchain-core` 工具模块：{exc}"

    tools: list[Any] = []
    for definition in list_registered_tools():
        if definition.permissions != "read":
            continue
        args_schema = _args_model_from_tool(definition)
        coroutine = _tool_coroutine(ctx, definition)
        tools.append(
            StructuredTool.from_function(
                coroutine=coroutine,
                name=definition.name,
                description=definition.description,
                args_schema=args_schema,
            )
        )
    return tools, None if tools else "没有可注册给 Agent 的只读工具。"


def _args_model_from_tool(definition: ToolDefinition) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    required = set(definition.schema.get("required", []))
    for name, prop in definition.schema.get("properties", {}).items():
        python_type = _python_type(prop.get("type"))
        default = ... if name in required else prop.get("default", None)
        fields[name] = (python_type, Field(default=default, description=prop.get("description") or name))
    model_name = "".join(part.capitalize() for part in definition.name.split("_")) + "Args"
    return create_model(model_name, **fields)  # type: ignore[no-any-return,call-overload]


def _python_type(json_type: str | None) -> Any:
    return {
        "array": list,
        "boolean": bool,
        "integer": int,
        "number": float,
        "object": dict,
        "string": str,
    }.get(json_type or "string", str)


def _tool_coroutine(ctx: AgentToolContext, definition: ToolDefinition):
    async def call_tool(**kwargs: Any) -> str:
        result = await execute_tool(ctx, definition.name, **kwargs)
        return json.dumps(_jsonable(result), ensure_ascii=False)

    call_tool.__name__ = definition.name
    call_tool.__doc__ = definition.description
    return call_tool


def _messages_from_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in history[-10:]:
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _extract_structured_response(response: Any) -> AgentAnalysisResult | None:
    if not isinstance(response, dict):
        return None
    value = response.get("structured_response")
    if isinstance(value, AgentAnalysisResult):
        return value
    if isinstance(value, dict):
        try:
            return AgentAnalysisResult.model_validate(value)
        except Exception:
            return None
    return None


def _extract_answer(response: Any) -> str:
    if isinstance(response, dict):
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            return _message_content(messages[-1])
        if response.get("output"):
            return str(response["output"])
    return _message_content(response)


def _message_content(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", message)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if inspect.isclass(value):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
