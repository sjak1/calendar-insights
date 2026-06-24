"""Probe which OSS models are enabled on this Bedrock account and whether
they accept tool configs via the Converse API. Throwaway script."""

import json

from bedrock_llm import _get_bedrock_client

CANDIDATES = [
    "openai.gpt-oss-120b-1:0",
    "openai.gpt-oss-20b-1:0",
    "us.meta.llama4-maverick-17b-instruct-v1:0",
    "us.meta.llama4-scout-17b-instruct-v1:0",
    "us.meta.llama3-3-70b-instruct-v1:0",
    "mistral.mistral-large-2407-v1:0",
    "us.deepseek.r1-v1:0",
    "qwen.qwen3-32b-v1:0",
    "qwen.qwen3-235b-a22b-2507-v1:0",
]

TOOL = {
    "tools": [
        {
            "toolSpec": {
                "name": "get_time",
                "description": "Get the current time in a timezone. Call this for any time question.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"],
                    }
                },
            }
        }
    ]
}


def try_model(client, model_id, with_tools):
    kwargs = {
        "modelId": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": "What time is it in Tokyo right now?"
                        if with_tools
                        else "Say hi in 3 words."
                    }
                ],
            }
        ],
        "inferenceConfig": {"maxTokens": 200},
    }
    if with_tools:
        kwargs["toolConfig"] = TOOL
    resp = client.converse(**kwargs)
    msg = resp["output"]["message"]
    stop = resp.get("stopReason")
    tool_called = any("toolUse" in b for b in msg.get("content", []))
    return stop, tool_called


def main():
    client = _get_bedrock_client()
    for mid in CANDIDATES:
        line = f"{mid:50s}"
        try:
            stop, _ = try_model(client, mid, with_tools=False)
            line += " basic=OK"
        except Exception as e:
            line += f" basic=FAIL ({type(e).__name__}: {str(e)[:90]})"
            print(line)
            continue
        try:
            stop, tool_called = try_model(client, mid, with_tools=True)
            line += f" tools=OK stop={stop} tool_called={tool_called}"
        except Exception as e:
            line += f" tools=FAIL ({type(e).__name__}: {str(e)[:90]})"
        print(line)


if __name__ == "__main__":
    main()
