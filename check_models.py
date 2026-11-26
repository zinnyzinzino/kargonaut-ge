"""Check which Gemini models work for this API key right now, and how fast.

Run:  python check_models.py
Then put the fastest working ones in KARGONAUT_MODELS in your .env file, e.g.
      KARGONAUT_MODELS=gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-flash-lite-latest
"""
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent / ".env")

# Candidates from your key's model list (text models suitable for a chat assistant)
CANDIDATES = [
    "gemini-3.5-flash-lite", "gemini-3.5-flash",
    "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest",
    "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash", "gemini-3-flash-preview",
    "gemini-2.5-flash",
]


def ping_tool():
    """Small tool, to check the model can do function calling (Kargonaut needs it)."""
    return {"ok": True}


client = genai.Client(http_options=types.HttpOptions(
    retry_options=types.HttpRetryOptions(attempts=1), timeout=25_000))
tool = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="ping_tool", description="Call this tool.",
    parameters_json_schema={"type": "object", "properties": {}})])

print(f"{'model':28} {'result':40} seconds")
working = []
for model in CANDIDATES:
    started = time.time()
    try:
        response = client.models.generate_content(
            model=model,
            contents="Call the ping_tool tool.",
            config=types.GenerateContentConfig(tools=[tool]),
        )
        parts = response.candidates[0].content.parts or []
        used_tool = any(p.function_call for p in parts)
        result = "OK, tool calling works" if used_tool else "OK, but did not call the tool"
        if used_tool:
            working.append((time.time() - started, model))
    except Exception as exc:
        code = getattr(exc, "code", None)
        result = f"FAILED {code or type(exc).__name__}"
    print(f"{model:28} {result:40} {time.time() - started:5.1f}")

if working:
    working.sort()
    print("\nWorking with tool calling, fastest first:")
    print("KARGONAUT_MODELS=" + ",".join(m for _, m in working))
else:
    print("\nNo model worked right now. If they all show 503/504, Google is overloaded: try again later.")