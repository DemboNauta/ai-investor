"""Quick test — Responses API for OpenAI and xAI. No file writes, no side effects."""
import os, json
from dotenv import load_dotenv
load_dotenv()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
XAI_MODEL    = os.getenv("GROK_MODEL", "grok-4.1-fast-reasoning")
XAI_API_KEY  = os.getenv("XAI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SYSTEM = "You are a test agent. Use the available tools to answer."

# Simple tool: evaluate an expression and return result
_TOOL_CALC = {
    "name": "calculate",
    "description": "Evaluate a simple math expression and return the result.",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "Math expression, e.g. '2+2'"},
        },
        "required": ["expression"],
    },
}

def handle_tool(name, args_str):
    args = json.loads(args_str)
    if name == "calculate":
        try:
            result = eval(args["expression"], {"__builtins__": {}})
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {e}"
    return f"Unknown tool: {name}"


# ── OpenAI Responses API ───────────────────────────────────────────────────────

def test_openai():
    print("\n=== OpenAI Responses API ===")
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Responses API tool format: no nested "function" key
    tool = {"type": "function", **_TOOL_CALC}

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM,
        input="What is 17 * 23? Use the calculate tool.",
        tools=[tool],
    )
    print(f"Response id: {response.id}")
    print(f"Output items: {[item.type for item in response.output]}")

    for item in response.output:
        if item.type == "function_call":
            print(f"  Tool call: {item.name}({item.arguments})")
            tool_result = handle_tool(item.name, item.arguments)
            print(f"  Tool result: {tool_result}")

            # Continue with tool result
            response2 = client.responses.create(
                model=OPENAI_MODEL,
                input=[{
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": tool_result,
                }],
                previous_response_id=response.id,
                tools=[tool],
            )
            print(f"  Final response id: {response2.id}")
            for out in response2.output:
                if out.type == "message":
                    for content in out.content:
                        if hasattr(content, "text"):
                            print(f"  Final answer: {content.text}")
            break
    else:
        # No tool call — print text response
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if hasattr(content, "text"):
                        print(f"  Direct answer (no tool): {content.text}")

    print("OpenAI OK")


# ── xAI SDK Responses API ──────────────────────────────────────────────────────

def test_xai():
    print("\n=== xAI SDK Responses API ===")
    from xai_sdk import Client
    from xai_sdk.chat import user, system, tool, tool_result

    client = Client(api_key=XAI_API_KEY)

    xai_tool = tool(
        name=_TOOL_CALC["name"],
        description=_TOOL_CALC["description"],
        parameters=_TOOL_CALC["parameters"],
    )

    chat = client.chat.create(
        model=XAI_MODEL,
        store_messages=True,
        tools=[xai_tool],
    )
    chat.append(system(SYSTEM))
    chat.append(user("What is 17 * 23? Use the calculate tool."))
    response = chat.sample()

    print(f"Response id: {response.id}")
    print(f"finish_reason: {response.finish_reason}")
    print(f"tool_calls count: {len(response.tool_calls)}")

    if response.tool_calls:
        for tc in response.tool_calls:
            print(f"  Tool call: {tc.function.name}({tc.function.arguments})")
            result = handle_tool(tc.function.name, tc.function.arguments)
            print(f"  Tool result: {result}")

            # Continue with tool result — new chat with previous_response_id
            chat2 = client.chat.create(
                model=XAI_MODEL,
                store_messages=True,
                previous_response_id=response.id,
                tools=[xai_tool],
            )
            chat2.append(tool_result(result, tool_call_id=tc.id))
            response2 = chat2.sample()

            print(f"  Final response id: {response2.id}")
            print(f"  Final answer: {response2.content}")
            break
    else:
        print(f"  Direct answer (no tool): {response.content}")

    print("xAI OK")


if __name__ == "__main__":
    try:
        test_openai()
    except Exception as e:
        print(f"OpenAI FAILED: {e}")

    try:
        test_xai()
    except Exception as e:
        print(f"xAI FAILED: {e}")
