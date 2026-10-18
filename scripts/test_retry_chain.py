"""
Fault-injection test for the LLM retry/fallback chain. No network, no quota.

Verifies the behaviours that matter, using a fake client:
  1. transient 503 on the primary -> SAME model retried, answer still produced
  2. 404 on the primary            -> immediately switches to the fallback
  3. primary 503 x N then dead     -> exhausts retries, THEN switches
  4. every model dead             -> raises (never returns a fake answer)

Run:  ./venv/bin/python scripts/test_retry_chain.py
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import app.core.llm as llm
from app.config import settings

PRIMARY = settings.llm_model
FALLBACKS = settings.fallback_models


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    """Stands in for client.models; each model has a scripted list of outcomes."""

    def __init__(self):
        self.plan: dict[str, list] = {}
        self.calls: list[str] = []

    def generate_content(self, model=None, contents=None, config=None):
        self.calls.append(model)
        queue = self.plan.get(model)
        if not queue:
            return FakeResponse("OK")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


fake = FakeClient()
llm.client = fake
llm.time.sleep = lambda s: None        # no real backoff during the test

E503 = Exception("503 UNAVAILABLE: high demand")
E404 = Exception("404 NOT_FOUND: this model is no longer available to new users")
E429 = Exception("429 RESOURCE_EXHAUSTED: quota")


def run(name, plan, expect_text=None, expect_raise=False, expect_calls=None):
    fake.models.plan = {k: list(v) for k, v in plan.items()}
    fake.models.calls.clear()
    err = ""
    try:
        text, model = llm._generate("hi")
        ok = not expect_raise and (expect_text is None or text == expect_text)
        detail = f"text={text!r} via={model}"
    except Exception as e:
        ok = expect_raise
        detail = f"raised {type(e).__name__}"
        err = f" ({e})"
    if expect_calls is not None:
        ok = ok and fake.models.calls == expect_calls
        detail += f" calls={fake.models.calls}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}{err}")
    return ok


results = [
    run("healthy call costs exactly one request",
        {PRIMARY: ["hi there"]},
        expect_text="hi there", expect_calls=[PRIMARY]),

    run("transient 503 twice -> retried on the SAME model",
        {PRIMARY: [E503, E503, "recovered"]},
        expect_text="recovered", expect_calls=[PRIMARY] * 3),

    run("429 quota error -> retried on the SAME model",
        {PRIMARY: [E429, "after-quota"]},
        expect_text="after-quota", expect_calls=[PRIMARY] * 2),

    run("404 on primary -> switches to fallback with NO wasted retries",
        {PRIMARY: [E404], FALLBACKS[0]: ["from-fallback"]},
        expect_text="from-fallback", expect_calls=[PRIMARY, FALLBACKS[0]]),

    run("primary 503 x all attempts -> THEN switches to fallback",
        {PRIMARY: [E503] * settings.llm_max_attempts, FALLBACKS[0]: ["ok-now"]},
        expect_text="ok-now",
        expect_calls=[PRIMARY] * settings.llm_max_attempts + [FALLBACKS[0]]),

    run("every model dead -> raises instead of inventing an answer",
        {m: [E404] for m in [PRIMARY, *FALLBACKS]},
        expect_raise=True),
]

# The chain must never contain a model this key cannot load (that was the bug:
# the configured fallbacks were retired 2.x ids answering 404).
dead_prefixes = ("gemini-2.0", "gemini-2.5")
bad = [m for m in [PRIMARY, *FALLBACKS] if m.startswith(dead_prefixes)]
print(f"[{'PASS' if not bad else 'FAIL'}] configured chain contains no retired 2.x model"
      f"\n        chain={[PRIMARY, *FALLBACKS]}")
results.append(not bad)

print(f"\nRETRY CHAIN: {'ALL PASS' if all(results) else 'SOME FAILED'}")
sys.exit(0 if all(results) else 1)
