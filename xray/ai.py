"""Optional: let a language model write the summary paragraph.

The rules never change: Python computes every number, the model only turns
those numbers into sentences. Before the text reaches the report it is
checked number by number — if the model invents a figure, its text is thrown
away and the plain summary is used instead.

Names of people and customers are replaced by placeholders before the request
leaves the machine, and put back afterwards, so client data stays home.

Providers (first one with credentials wins):
  github   GitHub Models, free with a GitHub account; inside GitHub Actions
           the built-in GITHUB_TOKEN works when the workflow grants
           `permissions: models: read`.
  gemini   Google AI Studio, free tier (GEMINI_API_KEY)
  groq     Groq, free tier (GROQ_API_KEY)
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
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": f"odoo-process-xray/{__version__}", **(extra_headers or {})},
        json={"model": model, "temperature": 0.2, "max_tokens": 400,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise AIUnavailable(f"{url} answered {response.status_code}: {response.text[:200]}")
    return response.json()["choices"][0]["message"]["content"].strip()


def _gemini(key, model, prompt):
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400}},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise AIUnavailable(f"Gemini answered {response.status_code}: {response.text[:200]}")
    return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


PROVIDERS = {
    "github": {
        "env": ("GITHUB_MODELS_TOKEN", "GITHUB_TOKEN"),
        "model": os.environ.get("XRAY_AI_MODEL", "openai/gpt-4o-mini"),
        "label": "GitHub Models",
        "call": lambda key, model, prompt: _chat("https://models.github.ai/inference/chat/completions",
                                                 key, model, prompt),
    },
    "gemini": {
        "env": ("GEMINI_API_KEY",),
        "model": os.environ.get("XRAY_AI_MODEL", "gemini-2.0-flash"),
        "label": "Google Gemini",
        "call": _gemini,
    },
    "groq": {
        "env": ("GROQ_API_KEY",),
        "model": os.environ.get("XRAY_AI_MODEL", "llama-3.3-70b-versatile"),
        "call": lambda key, model, prompt: _chat("https://api.groq.com/openai/v1/chat/completions",
                                                 key, model, prompt),
        "label": "Groq",
    },
}


def pick_provider(name="auto"):
    names = list(PROVIDERS) if name == "auto" else [name]
    for candidate in names:
        provider = PROVIDERS.get(candidate)
        if not provider:
            raise AIUnavailable(f"Unknown AI provider '{candidate}'. Choose from: {', '.join(PROVIDERS)}.")
        for variable in provider["env"]:
            if os.environ.get(variable):
                return candidate, provider, os.environ[variable]
    raise AIUnavailable("No API key found. Set GITHUB_TOKEN (GitHub Models), GEMINI_API_KEY or GROQ_API_KEY.")


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
            name, config, key = pick_provider(provider)
            log(f"Asking {config['label']} ({config['model']}) for the summary...")
            text = config["call"](key, config["model"], prompt)
            label = f"{config['label']}, {config['model']}"
        else:  # tests and custom integrations
            text, label = call(prompt), "custom model"
    except AIUnavailable as e:
        return None, str(e)
    except Exception as e:  # network, quota, unexpected answer shape
        return None, f"{type(e).__name__}: {e}"

    invented = unsupported_numbers(text, data)
    if invented:
        return None, f"the model used numbers that are not in the analysis: {', '.join(invented[:5])}"
    # longest first, so "Customer 1" never eats "Customer 11"
    for placeholder in sorted(hidden, key=len, reverse=True):
        text = text.replace(placeholder, hidden[placeholder])
    note = (f"Written by {label} from the numbers in this report"
            + (", on anonymised data" if anonymised else "")
            + ". Every number was checked against the analysis.")
    return " ".join(text.split()), note
