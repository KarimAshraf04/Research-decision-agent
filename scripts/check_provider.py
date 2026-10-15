"""Quick check that the configured LLM provider(s) work for this project (about 20 seconds).

For each role (smart / fast) it tests what the agents need: a plain answer, a tool call and structured
(Pydantic) output - so with two providers (e.g. Gemini + Groq) both are verified.
    python scripts/check_provider.py
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from pydantic import BaseModel  # noqa: E402

from agents import Agent, Runner, function_tool  # noqa: E402

from rdi import config, providers  # noqa: E402


class Capital(BaseModel):
    country: str
    capital: str


class Sum(BaseModel):
    a: int
    b: int
    total: int


@function_tool
def add(a: int, b: int) -> int:
    """Add two integers.

    Args:
        a: first number
        b: second number
    """
    return a + b


async def check_role(role: str) -> bool:
    model = providers.model_for(role)
    print(f"\n[{role}] provider={config.ROLE_PROVIDER[role]} models (fallback order): {providers.chain_label(role)}")
    checks = [
        ("plain answer", Agent(name="ping", model=model, instructions="Answer in one word."), "Say OK."),
        ("tool calling", Agent(name="calc", model=model, tools=[add],
                               instructions="Use the add tool, then answer with the number only."), "What is 17 + 25?"),
        ("structured output", Agent(name="geo", model=model, output_type=Capital,
                                    instructions="Return the country and its capital."), "Egypt"),
        # The specialists need BOTH at once: tools during research + a Pydantic object at the end.
        ("tools + structured output", Agent(name="calc2", model=model, tools=[add], output_type=Sum,
                                            instructions="Use the add tool, then return the result."), "17 + 25"),
    ]
    ok = True
    for label, agent, prompt in checks:
        try:
            result = await Runner.run(agent, prompt, max_turns=8)
            used = "; ".join(providers.drain_notices())
            print(f"  PASS  {label}: {result.final_output}" + (f"   [{used}]" if used else ""))
        except Exception as e:
            ok = False
            print(f"  FAIL  {label}: {type(e).__name__}: {str(e)[:300]}")
    return ok


async def main() -> int:
    print(f"Providers: {config.PROVIDER_LABEL}")
    try:
        providers.configure()
    except RuntimeError as e:
        print(f"FAIL  configuration: {e}")
        return 1
    roles = ["smart"] if config.PROVIDER_SMART == config.PROVIDER_FAST and config.MODEL_SMART == config.MODEL_FAST \
        else ["smart", "fast"]
    results = [await check_role(r) for r in roles]
    if not all(results):
        print("\nHints: check the API key(s) in .env; if a model is 'not found', set RDI_MODEL_SMART / RDI_MODEL_FAST "
              "to a model listed in that provider's console; on 429 errors wait a minute (free-tier rate limit).")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
