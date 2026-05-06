"""
Bedrock LLM client for Converse API with tool calling support.
Replaces OpenAI for the main query processor.
"""

import json
import os
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from dotenv import load_dotenv

load_dotenv()

# Model ID - Claude Haiku on Bedrock (cross-region inference)
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID") or "us.anthropic.claude-sonnet-4-6"
BEDROCK_REGION = os.getenv("AWS_REGION", os.getenv("BEDROCK_REGION", "us-west-2"))

_bedrock_client = None


def _get_bedrock_client():
    """Return a singleton Bedrock runtime client.
    Uses bedrock_api_key or BEDROCK_API_KEY from env as AWS_BEARER_TOKEN_BEDROCK
    so boto3 picks it up for API key auth (instead of IAM).
    """
    global _bedrock_client
    if _bedrock_client is None:
        # Bedrock API key: boto3 reads AWS_BEARER_TOKEN_BEDROCK for API key auth
        api_key = os.getenv("bedrock_api_key") or os.getenv("BEDROCK_API_KEY")
        if api_key:
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = api_key
        _bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    return _bedrock_client


def openai_tools_to_bedrock(openai_tools: List[Dict]) -> List[Dict]:
    """
    Convert OpenAI function tool definitions to Bedrock toolSpec format.
    OpenAI: {"type": "function", "name": "...", "description": "...", "parameters": {...}}
    Bedrock: {"toolSpec": {"name": "...", "description": "...", "inputSchema": {"json": {...}}}}
    """
    bedrock_tools = []
    for t in openai_tools:
        if t.get("type") != "function":
            continue
        params = t.get("parameters", {})
        # Bedrock inputSchema uses "json" key with the schema
        input_schema = {
            "type": params.get("type", "object"),
            "properties": params.get("properties", {}),
            "required": params.get("required", []),
        }
        # Filter out empty required
        if not input_schema["required"]:
            input_schema.pop("required", None)
        bedrock_tools.append({
            "toolSpec": {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {"json": input_schema},
            }
        })
    return bedrock_tools


def _to_bedrock_message(item: Dict) -> Optional[Dict]:
    """
    Convert a message from OpenAI/session format to Bedrock Converse format.
    Handles: user, assistant, function_call_output (tool result).
    """
    role = item.get("role")
    content = item.get("content")
    msg_type = item.get("type")

    # Tool result (function_call_output)
    if msg_type == "function_call_output":
        call_id = item.get("call_id")
        output = item.get("output", "")
        return {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": call_id,
                        "content": [{"text": str(output)}],
                        "status": "success",
                    }
                }
            ],
        }

    # User or assistant
    if role in ("user", "assistant"):
        # Assistant message may already be in Bedrock format (dict with "content" array)
        if role == "assistant" and isinstance(content, dict) and "content" in content:
            blocks = list(content["content"])  # copy so we don't mutate
            # Bedrock requires the first content block to have a non-blank text field.
            # If the first block is toolUse-only (no text), prepend a placeholder.
            first = blocks[0] if blocks else {}
            if blocks and (not first.get("text") or not str(first.get("text", "")).strip()):
                blocks = [{"text": " "}] + blocks
            return {"role": "assistant", "content": blocks}
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        text = block.get("text", "")
                        break
                    if block.get("type") == "output_text" and hasattr(block.get("output_text"), "__str__"):
                        text = str(block.get("output_text", ""))
                        break
        if not text and isinstance(content, str):
            text = content
        return {
            "role": role,
            "content": [{"text": text}],
        }

    return None


def converse(
    messages: List[Dict],
    system,
    tool_config: Dict,
    model_id: Optional[str] = None,
) -> Dict:
    """
    Call Bedrock Converse API.

    `system` accepts either a plain string (wrapped as a single text block)
    or a pre-built list of Bedrock system content blocks — use the list form
    to insert ``{"cachePoint": {"type": "default"}}`` markers for prompt
    caching of static prefixes.

    Returns the raw response dict.
    """
    client = _get_bedrock_client()
    bedrock_messages = []
    i = 0
    while i < len(messages):
        item = messages[i]
        if not isinstance(item, dict):
            i += 1
            continue
        if item.get("type") == "function_call":
            i += 1
            continue  # Don't send raw function_call to Bedrock; we send tool results

        # Coalesce consecutive function_call_output into one "user" message with multiple toolResult blocks
        if item.get("type") == "function_call_output":
            tool_result_blocks = []
            while i < len(messages) and isinstance(messages[i], dict) and messages[i].get("type") == "function_call_output":
                sub = messages[i]
                call_id = sub.get("call_id")
                output = sub.get("output", "")
                tool_result_blocks.append({
                    "toolResult": {
                        "toolUseId": call_id,
                        "content": [{"text": str(output)}],
                        "status": "success",
                    }
                })
                i += 1
            if tool_result_blocks:
                bedrock_messages.append({
                    "role": "user",
                    "content": tool_result_blocks,
                })
            continue

        converted = _to_bedrock_message(item)
        if converted:
            bedrock_messages.append(converted)
        i += 1

    if isinstance(system, list):
        system_content = system
    else:
        system_content = [{"text": system}] if system else []
    response = client.converse(
        modelId=model_id or BEDROCK_MODEL_ID,
        messages=bedrock_messages,
        system=system_content,
        toolConfig=tool_config,
    )
    return response
