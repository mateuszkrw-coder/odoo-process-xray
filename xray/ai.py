"""Optional: let a language model write the summary paragraph.

The rules never change: Python computes every number, the model only turns
those numbers into sentences. Before the text reaches the report it is
checked number by number — if the model invents a figure, its text is thrown
away and the plain summary is used instead.

Names of people and customers are replaced by placeholders before the request
leaves the machine, and put back afterwards, so client data stays home.

Providers (the first one with credentials wins):
  gemini   Google AI Studio, free tier (GEMINI_API_KEY)
  groq     Groq, free tier (GROQ_API_KEY)
  custom   any OpenAI-compatible endpoint (XRAY_AI_URL, XRAY_AI_KEY, XRAY_AI_MODEL),
           for OpenRouter, Mistral, Azure, a local model...

Model names and free tiers change often (GitHub Models, for example, was
retired in July 2026), so each provider carries a list of candidate models and
moves on to the next when one is unknown.
"""
import json
import os
import re

import requests

from . import __version__

TIMEOUT = 60

PROMPT = """You are a business analyst writing the opening of a report about a company's
order-to-cash process in Odoo. Below is the computed analysis, in JSON.

Write 3 to 5 short sentences for the management team:
- start with the state of the process as a whole (volume, conversion, order-to-cash time),
- then the two or three findings that matter most, and where they are concentrated,
- end with the single action you would take first.

Rules:
- Use ONLY numbers that appear in the JSON. Never calculate or estimate a new number.
- Keep names exactly as written (they are placeholders like "Salesperson A").
- Plain business English, no bullet points, no headings, no markdown.

JSON:
"""


class AIUnavailable(Exception):
    pass


# --------------------------------------------------------------------------
# What the model is allowed to see
# --------------------------------------------------------------------------

def anonymise(results, enabled=True):
    """Replace people and customer names with placeholders. Returns the map back."""
    if not enabled:
        return {}
    back = {}
    for label, values in (("Salesperson", sorted({c["salesperson"] for c in results.cases if c["salesperson"]})),
                          ("Customer", sorted({c["customer"] for c in results.cases if c["customer"]}))):
        for i, name in enumerate(values, start=1):
            placeholder = f"{label} {chr(64 + i) if label == 'Salesperson' and i <= 26 else i}"
            back[placeholder] = name
    return back


def facts(results, hidden):
    """The analysis as plain data: the only thing the model is given."""
    forward = {real: fake for fake, real in hidden.items()}
    mask = lambda name: forward.get(name, name)

    steps = {s.label: {"median_days": round(s.median_days, 1) if s.median_days is not None else None,
                       "orders": s.n} for s in results.steps + [results.order_to_cash]}
    findings = []
    for r in results.rules:
        if not r.hits:
            continue
        item = {"problem": r.rule.title, "orders_affected": len(r.hits),
                "out_of": r.applicable, "share_percent": round(r.rate * 100)}
        if r.concentration:
            c = r.concentration[0]
            item["concentrated_in"] = {
                "kind": c.dimension,
                "values": [mask(v) for v in c.values],
                "share_of_problem_percent": round(c.hit_share * 100),
                "share_of_orders_percent": round(c.case_share * 100),
                "rate_inside_group_percent": round(c.rate * 100),
            }
        findings.append(item)
    bottlenecks = [{"warehouse": b["warehouse"],
                    "slow_days": [{"weekday": d[0], "median_working_days": round(d[1], 1), "orders": d[2]}
                                  for d in b["slow_days"]],
                    "normal_median_working_days": round(b["typical_days"], 1)}
                   for b in results.bottlenecks]
    return {
        "company": results.company,
        "period": [results.period[0].strftime("%Y-%m-%d"), results.period[1].strftime("%Y-%m-%d")],
        "orders": {"quotations": results.counts["quotations"], "confirmed": results.counts["confirmed"],
                   "conversion_percent": round(results.counts["conversion"] * 100),
                   "shipped": results.counts["shipped"], "invoiced": results.counts["invoiced"],
                   "paid": results.counts["paid"]},
        "median_days_per_step": steps,
        "findings": sorted(findings, key=lambda f: -f["orders_affected"]),
        "slow_weekdays": bottlenecks,
    }


# --------------------------------------------------------------------------
# Checking the model's arithmetic (there should be none)
# --------------------------------------------------------------------------

def allowed_numbers(data):
    numbers = set()

    def walk(value):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            numbers.add(float(value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            for match in re.findall(r"\d+(?:\.\d+)?", value):
                numbers.add(float(match))

    walk(data)
    return numbers


def unsupported_numbers(text, data):
    """Numbers in the text that don't come from the analysis."""
    allowed = allowed_numbers(data)
    bad = []
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        value = float(token.replace(",", ""))
        if not any(abs(value - a) <= max(0.5, 0.01 * abs(a)) for a in allowed):
            bad.append(token)
    return bad


# --------------------------------------------------------------------------
# Providers (all OpenAI-compatible except Gemini)
# --------------------------------------------------------------------------

def _chat(url, key, model, prompt, extra_headers=None):
    """OpenAI-compatible chat completion.

    Older models want `max_tokens`, newer ones only accept
    `max_completion_tokens`, so a rejection is retried the other way.
    """
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "User-Agent": f"odoo-process-xray/{__version__}", **(extra_headers or {})}
    body = {"model": model, "temperature": 0.2, "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}]}
    response = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
    if response.status_code == 400 and "max_tokens" in response.text:
        body["max_completion_tokens"] = body.pop("max_tokens")
        body.pop("temperature", None)
        response = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
    if response.status_code != 200:
        raise AIUnavailable(f"{url} answered {response.status_code}: {response.text[:300]}")
    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError):
        raise AIUnavailable(f"unexpected answer from {url}: {response.text[:300]}")


def _gemini(key, model, prompt):
    """Google AI Studio.

    Recent Gemini models spend part of the output budget on internal
    reasoning, which silently truncates the answer, so thinking is switched
    off and a cut-off answer is treated as a failure.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    config = {"temperature": 0.2, "maxOutputTokens": 1200, "thinkingConfig": {"thinkingBudget": 0}}
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config}
    response = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                             json=body, timeout=TIMEOUT)
    if response.status_code == 400 and "thinking" in response.text.lower():
        config.pop("thinkingConfig")
        response = requests.post(url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                 json=body, timeout=TIMEOUT)
    if response.status_code != 200:
        raise AIUnavailable(f"Gemini answered {response.status_code}: {response.text[:300]}")
    try:
        candidate = response.json()["candidates"][0]
        parts = [p["text"] for p in candidate["content"]["parts"] if p.get("text") and not p.get("thought")]
    except (KeyError, IndexError, ValueError):
        raise AIUnavailable(f"unexpected answer from Gemini: {response.text[:300]}")
    if candidate.get("finishReason") not in (None, "STOP"):
        raise AIUnavailable(f"Gemini stopped early ({candidate.get('finishReason')})")
    return "".join(parts).strip()


def _openai_compatible(url):
    def call(key, model, prompt):
        return _chat(url, key, model, prompt)
    return call


PROVIDERS = {
    "gemini": {
        "env": ("GEMINI_API_KEY",),
        "models": ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"],
        "label": "Google Gemini",
        "call": _gemini,
    },
    "groq": {
        "env": ("GROQ_API_KEY",),
        "models": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"],
        "label": "Groq",
        "call": _openai_compatible("https://api.groq.com/openai/v1/chat/completions"),
    },
    "custom": {
        "env": ("XRAY_AI_KEY",),
        "models": [os.environ.get("XRAY_AI_MODEL", "gpt-4o-mini")],
        "label": "custom endpoint",
        "call": lambda key, model, prompt: _chat(os.environ.get("XRAY_AI_URL", ""), key, model, prompt),
    },
}


def pick_provider(name="auto"):
    """First provider with a key. Returns (config, key)."""
    names = list(PROVIDERS) if name == "auto" else [name]
    for candidate in names:
        provider = PROVIDERS.get(candidate)
        if not provider:
            raise AIUnavailable(f"Unknown AI provider '{candidate}'. Choose from: {', '.join(PROVIDERS)}.")
        for variable in provider["env"]:
            if os.environ.get(variable):
                return provider, os.environ[variable]
    raise AIUnavailable("No API key found. Set GEMINI_API_KEY, GROQ_API_KEY or XRAY_AI_KEY "
                        "(with XRAY_AI_URL) to switch the summary on.")


def ask(provider, key, prompt, log=print):
    """Try the provider's models in order; an unknown model is not a failure."""
    models = [m for m in ([os.environ["XRAY_AI_MODEL"]] if os.environ.get("XRAY_AI_MODEL") else [])
              + provider["models"] if m]
    last = None
    for model in models:
        try:
            log(f"Asking {provider['label']} ({model}) for the summary...")
            return provider["call"](key, model, prompt), f"{provider['label']}, {model}"
        except AIUnavailable as e:
            last = e
            if not any(word in str(e).lower() for word in ("not found", "404", "does not exist",
                                                           "unknown model", "decommission", "unsupported")):
                raise
    raise last or AIUnavailable("no model available")


# --------------------------------------------------------------------------
# The one function the report uses
# --------------------------------------------------------------------------

def write_summary(results, provider="auto", anonymised=True, call=None, log=print):
    """Return (text, note) or (None, reason). Never raises."""
    hidden = anonymise(results, anonymised)
    data = facts(results, hidden)
    prompt = PROMPT + json.dumps(data, indent=1, ensure_ascii=False)
    try:
        if call is None:
            config, key = pick_provider(provider)
            text, label = ask(config, key, prompt, log)
        else:  # tests and custom integrations
            text, label = call(prompt), "custom model"
    except AIUnavailable as e:
        return None, str(e)
    except Exception as e:  # network, quota, unexpected answer shape
        return None, f"{type(e).__name__}: {e}"

    text = " ".join(text.split())
    if len(text) < 120 or text[-1] not in ".!?":
        return None, f"the model's answer looks cut off: {text[:80]!r}"

    invented = unsupported_numbers(text, data)
    if invented:
        return None, f"the model used numbers that are not in the analysis: {', '.join(invented[:5])}"
    # longest first, so "Customer 1" never eats "Customer 11"
    for placeholder in sorted(hidden, key=len, reverse=True):
        text = text.replace(placeholder, hidden[placeholder])
    note = (f"Written by {label} from the numbers in this report"
            + (", on anonymised data" if anonymised else "")
            + ". Every number was checked against the analysis.")
    return text, note
