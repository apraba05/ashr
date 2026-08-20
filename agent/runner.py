"""Run frozen LangChain agent scenarios and optionally record Redis goldens."""

import argparse
import asyncio
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings(
    "ignore", message="Field 'lifespan' has an incomplete definition"
)

import redis
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.prompts import ChatPromptTemplate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_FILE = ROOT / "scenarios" / "scenarios.json"
TOOL_SERVER = ROOT / "agent" / "tool_server.py"

BASELINE_SYSTEM_PROMPT = (
    "Answer using lookup_policy. Call policy keys in the order they appear in the question."
)
REGRESSED_SYSTEM_PROMPT = (
    "Answer using lookup_policy. Call policy keys in alphabetical key order."
)

POLICY_TERMS = {
    "refund_window": "refund",
    "primary_region": "region",
    "support_sla": "support",
    "audit_retention": "audit",
}


class BedrockCompatibleMock(BaseChatModel):
    """Deterministic stand-in implementing LangChain's Bedrock chat contract."""

    @property
    def _llm_type(self) -> str:
        return "bedrock-compatible-mock"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
        if tool_messages:
            tool_call_message = next(
                message
                for message in reversed(messages)
                if isinstance(message, AIMessage) and message.tool_calls
            )
            values = {
                message.tool_call_id: message.content for message in tool_messages
            }
            answer = "; ".join(
                f"{call['args']['key']}={values[call['id']]}"
                for call in tool_call_message.tool_calls
            )
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=answer))])

        question = next(
            message.content for message in messages if isinstance(message, HumanMessage)
        )
        system_text = str(messages[0].content)
        keys = [
            key
            for key, term in sorted(
                POLICY_TERMS.items(), key=lambda item: question.lower().find(item[1])
            )
            if term in question.lower()
        ]
        if "alphabetical key order" in system_text:
            keys.sort()

        calls = [
            {
                "name": "lookup_policy",
                "args": {"key": key},
                "id": f"call_{index}",
                "type": "tool_call",
            }
            for index, key in enumerate(keys, start=1)
        ]
        message = AIMessage(content="", tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


async def run_scenarios(prompt_version: str) -> List[Dict[str, Any]]:
    scenarios = json.loads(SCENARIOS_FILE.read_text())
    system_prompt = (
        BASELINE_SYSTEM_PROMPT
        if prompt_version == "baseline"
        else REGRESSED_SYSTEM_PROMPT
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{question}")]
    )
    model = BedrockCompatibleMock()
    server = StdioServerParameters(command=sys.executable, args=[str(TOOL_SERVER)])
    results: List[Dict[str, Any]] = []

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for scenario in scenarios:
                messages = prompt.format_messages(question=scenario["prompt"])
                tool_request = model.invoke(messages)
                trace = []
                tool_messages = []
                for call in tool_request.tool_calls:
                    response = await session.call_tool(call["name"], call["args"])
                    value = response.content[0].text
                    trace.append(
                        {"tool": call["name"], "arguments": call["args"], "result": value}
                    )
                    tool_messages.append(
                        ToolMessage(content=value, tool_call_id=call["id"])
                    )
                final = model.invoke(messages + [tool_request] + tool_messages)
                results.append(
                    {
                        "scenario_id": scenario["id"],
                        "prompt": scenario["prompt"],
                        "tool_calls": trace,
                        "final_answer": final.content,
                    }
                )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["record", "run"])
    parser.add_argument(
        "--prompt-version", choices=["baseline", "regressed"], default="baseline"
    )
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--output", type=Path, default=ROOT / "current")
    args = parser.parse_args()

    results = asyncio.run(run_scenarios(args.prompt_version))
    if args.mode == "record":
        client = redis.from_url(args.redis_url, decode_responses=True)
        for result in results:
            client.set(
                f"golden:{result['scenario_id']}",
                json.dumps(result, sort_keys=True),
            )
        print(f"Recorded {len(results)} golden scenarios in Redis")
        return

    args.output.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = args.output / f"{result['scenario_id']}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        f"Ran {len(results)} scenarios with prompt={args.prompt_version}; "
        f"wrote {args.output}"
    )


if __name__ == "__main__":
    main()
