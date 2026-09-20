"""The AI summary is optional, grounded and checked. These tests use a fake model."""
from datetime import datetime, timezone

from xray.ai import anonymise, facts, unsupported_numbers, write_summary
from xray.analyze import analyze
from xray.report import render

AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def results_of(log):
    return analyze(log, company="Beanline", as_of=AS_OF)


def test_names_never_leave_the_machine(synthetic_log):
    results = results_of(synthetic_log)
    hidden = anonymise(results)
    data = facts(results, hidden)
    assert "Tom" not in str(data)
    assert any(v.startswith("Salesperson ") for group in
               [f["concentrated_in"]["values"] for f in data["findings"] if "concentrated_in" in f]
               for v in group)


def test_real_names_are_used_when_asked(synthetic_log):
    results = results_of(synthetic_log)
    data = facts(results, anonymise(results, enabled=False))
    assert "Tom" in str(data)


def test_good_summary_is_kept_and_names_restored(synthetic_log):
    results = results_of(synthetic_log)

    def model(prompt):
        assert "Tom" not in prompt  # the model only ever sees placeholders
        return ("The company confirmed 200 of its 200 quotations in the period, and cash arrives a median "
                "of 24.2 days after confirmation. Salesperson D changed 47 orders after the customer had "
                "already confirmed them, which is where I would start.")

    text, note = write_summary(results, call=model)
    assert text.startswith("The company confirmed 200 of its 200 quotations")
    assert "Salesperson D" not in text and "Tom" in text
    assert "checked against the analysis" in note


def test_invented_numbers_are_rejected(synthetic_log):
    results = results_of(synthetic_log)
    text, reason = write_summary(results, call=lambda prompt: "Orders take 7654 days and cost 4321 euro.")
    assert text is None
    assert "7654" in reason


def test_cut_off_answers_are_rejected(synthetic_log):
    results = results_of(synthetic_log)
    text, reason = write_summary(results, call=lambda prompt: "Across the period, the company generated")
    assert text is None and "cut off" in reason


def test_broken_provider_does_not_break_the_report(synthetic_log):
    def model(prompt):
        raise ConnectionError("no network")

    results = results_of(synthetic_log)
    text, reason = write_summary(results, call=model)
    assert text is None and "no network" in reason
    html = render(results, ai_summary=(text, reason))
    assert "Key findings" in html and "no network" not in html


def test_summary_appears_in_the_report(synthetic_log):
    results = results_of(synthetic_log)
    html = render(results, ai_summary=("Everything is fine.", "Written by a test model."))
    assert "Everything is fine." in html and "Written by a test model." in html


def test_bullets_are_rendered_as_a_list(synthetic_log):
    results = results_of(synthetic_log)
    summary = "\n".join([
        "The company confirmed 200 of 200 quotations, with cash in 24.2 days.",
        "- Salesperson D changed 47 orders after confirmation.",
        "- 200 orders were shipped on time.",
        "First action: lock confirmed orders.",
    ])
    html = render(results, ai_summary=(summary, "Written by a test model."))
    assert "<ul class=\"written-points\">" in html
    assert html.count("<li>Salesperson D changed 47 orders after confirmation.</li>") == 1
    assert "<p>First action: lock confirmed orders.</p>" in html


def test_unsupported_numbers_tolerates_rounding():
    data = {"share": 17.4, "orders": 1200}
    assert unsupported_numbers("17% of 1,200 orders", data) == []
    assert unsupported_numbers("19% of orders", data) == ["19"]
