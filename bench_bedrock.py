"""
Standalone Bedrock latency bench. No FastAPI, no app code — just boto3.

Purpose: confirm whether the response times we see in the app are actually
inherent to Bedrock for these models, or whether our pipeline is adding
overhead. Tests Sonnet 4.6 vs Haiku 4.5 across input sizes and output sizes,
warm vs cold cache.

Run:
    source venv/bin/activate
    python bench_bedrock.py
"""

import os
import statistics
import time
from typing import List, Optional

import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", os.getenv("BEDROCK_REGION", "us-west-2"))
SONNET = "us.anthropic.claude-sonnet-4-6"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Wire up the same auth path as bedrock_llm.py
_api_key = os.getenv("bedrock_api_key") or os.getenv("BEDROCK_API_KEY")
if _api_key:
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = _api_key

_client = boto3.client("bedrock-runtime", region_name=REGION)


def call(model_id: str, system_text: str, user_text: str,
         max_tokens: int = 256, use_cache: bool = False):
    """Single Converse call. Returns (wall_seconds, usage_dict, output_text)."""
    if use_cache and len(system_text) > 2000:
        # cachePoint requires the prefix to be substantial; split with marker.
        system_blocks = [{"text": system_text}, {"cachePoint": {"type": "default"}}]
    else:
        system_blocks = [{"text": system_text}] if system_text else []

    t0 = time.time()
    resp = _client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        system=system_blocks,
        inferenceConfig={"maxTokens": max_tokens},
    )
    elapsed = time.time() - t0

    usage = resp.get("usage", {})
    text = ""
    for blk in resp["output"]["message"]["content"]:
        if "text" in blk:
            text += blk["text"]
    return elapsed, usage, text


def bench(label: str, model_id: str, system_text: str, user_text: str,
          max_tokens: int, runs: int = 3, use_cache: bool = False):
    short = "haiku" if "haiku" in model_id else "sonnet"
    print(f"\n── {label} [{short}] ───────────────────────────────")
    print(f"   sys_chars={len(system_text)}  user_chars={len(user_text)}  max_out={max_tokens}  cache={use_cache}")
    times: List[float] = []
    last_usage = {}
    for i in range(runs):
        elapsed, usage, _ = call(model_id, system_text, user_text, max_tokens, use_cache)
        times.append(elapsed)
        last_usage = usage
        out_tok = usage.get("outputTokens", 0)
        in_tok = usage.get("inputTokens", 0)
        cr = usage.get("cacheReadInputTokens", 0)
        cw = usage.get("cacheWriteInputTokens", 0)
        rate = (elapsed * 1000 / out_tok) if out_tok else 0.0
        cache_str = f"  cache_r={cr} cache_w={cw}" if (cr or cw) else ""
        print(f"   run {i+1}: {elapsed:5.2f}s  in={in_tok:5d}  out={out_tok:4d}  → {rate:5.1f} ms/out_tok{cache_str}")
    if len(times) > 1:
        print(f"   median: {statistics.median(times):5.2f}s   min: {min(times):5.2f}s   max: {max(times):5.2f}s")
    return times, last_usage


def main():
    print(f"Region: {REGION}")
    print(f"Sonnet: {SONNET}")
    print(f"Haiku:  {HAIKU}")

    # Long system prompt that approximates our 10k-token AI_INSTRUCTIONS.
    # Pad with realistic-looking text so token counts are similar.
    BIG_SYSTEM = (
        "You are a helpful business analyst. Follow these instructions exactly.\n"
        + ("- Always respond in concise markdown bullet form.\n"
           "- Never reveal internal SQL or tool args.\n"
           "- Use the user's name if provided.\n"
           "- Output dates as YYYY-MM-DD.\n"
           "- Cite specific event IDs when available.\n"
           "- Refer to the schema below for field paths.\n"
           "- Prefer .keyword for filters and exact-match.\n"
           "- For date ranges always use epoch_millis format.\n"
           "- Avoid emoji and avoid tables unless asked.\n"
           "- Trim verbose output.\n") * 200  # ~10k tokens
    )

    # 1. Pure latency floor — tiny input, tiny output
    bench("1. Latency floor — tiny in, tiny out",
          SONNET, "be brief", "say hi in 3 words", max_tokens=10, runs=3)
    bench("1. Latency floor — tiny in, tiny out",
          HAIKU, "be brief", "say hi in 3 words", max_tokens=10, runs=3)

    # 2. Output throughput — tiny input, ~200 output tokens
    bench("2. Output throughput — tiny in, ~200 out",
          SONNET, "", "Write a 200-word paragraph about the history of databases. Be detailed.",
          max_tokens=300, runs=3)
    bench("2. Output throughput — tiny in, ~200 out",
          HAIKU, "", "Write a 200-word paragraph about the history of databases. Be detailed.",
          max_tokens=300, runs=3)

    # 3. Input processing — big system prompt, tiny output (no cache)
    bench("3. Input processing — 10k system, tiny out (NO cache)",
          SONNET, BIG_SYSTEM, "respond with the single word: ok", max_tokens=8, runs=3)
    bench("3. Input processing — 10k system, tiny out (NO cache)",
          HAIKU, BIG_SYSTEM, "respond with the single word: ok", max_tokens=8, runs=3)

    # 4. Same as #3 but WITH cachePoint — first call writes, rest read
    bench("4. Input processing — 10k system, tiny out (cachePoint)",
          SONNET, BIG_SYSTEM, "respond with the single word: ok", max_tokens=8, runs=3, use_cache=True)
    bench("4. Input processing — 10k system, tiny out (cachePoint)",
          HAIKU, BIG_SYSTEM, "respond with the single word: ok", max_tokens=8, runs=3, use_cache=True)

    # 5. Realistic mix — big system + ~200 output tokens (mimics our synthesis turn)
    bench("5. Realistic — 10k system, ~200 out (cachePoint)",
          SONNET, BIG_SYSTEM,
          "Summarise this in 5 bullet points: cats are nocturnal predators with retractable claws and excellent night vision; they descended from desert wildcats and were domesticated about 9000 years ago; they communicate through vocalisations, body language, and scent marking; they sleep 12 to 16 hours a day; modern breeds vary widely in size and coat.",
          max_tokens=300, runs=3, use_cache=True)
    bench("5. Realistic — 10k system, ~200 out (cachePoint)",
          HAIKU, BIG_SYSTEM,
          "Summarise this in 5 bullet points: cats are nocturnal predators with retractable claws and excellent night vision; they descended from desert wildcats and were domesticated about 9000 years ago; they communicate through vocalisations, body language, and scent marking; they sleep 12 to 16 hours a day; modern breeds vary widely in size and coat.",
          max_tokens=300, runs=3, use_cache=True)

    print("\n──────────────────────────────────────────────")
    print("Done. Compare ms/out_tok across rows: cache helps INPUT processing,")
    print("output rate is the dominant cost when output > 100 tokens.")


if __name__ == "__main__":
    main()
