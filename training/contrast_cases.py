"""Curated contrast families for controller-model routing boundaries.

These cases are synthetic but explicitly labelled. They contain no user
history, answers, Kairos prose, or private knowledge. Variants from one family
stay in the same split so benchmark scores cannot rely on template leakage.
"""
from __future__ import annotations

from typing import Any, Iterable


def _add(
    cases: list[dict[str, Any]],
    *,
    family: str,
    split: str,
    route: str,
    profile: str,
    inputs: Iterable[str],
    pipeline_mode: str = "auto",
) -> None:
    for index, text in enumerate(inputs, start=1):
        cases.append({
            "id": f"{family}-{index:03d}",
            "family": family,
            "split": split,
            "input": text,
            "pipeline_mode": pipeline_mode,
            "expected_route_kind": route,
            "expected_task_profile": profile,
        })


def build_contrast_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    capitals = [
        ("Japan", "Tokyo"), ("Canada", "Ottawa"), ("Brazil", "Brasilia"),
        ("Italy", "Rome"), ("Spain", "Madrid"), ("Thailand", "Bangkok"),
        ("Egypt", "Cairo"), ("Norway", "Oslo"), ("Argentina", "Buenos Aires"),
        ("Kenya", "Nairobi"), ("South Korea", "Seoul"), ("Portugal", "Lisbon"),
    ]
    _add(
        cases,
        family="small-factual-capital-train",
        split="train",
        route="small_task",
        profile="local_language",
        inputs=[f"What is the capital of {country}?" for country, _ in capitals[:8]],
    )
    _add(
        cases,
        family="small-factual-capital-test",
        split="test",
        route="small_task",
        profile="local_language",
        inputs=[f"Name the capital city of {country}." for country, _ in capitals[8:]],
    )

    _add(
        cases,
        family="small-arithmetic-train",
        split="train",
        route="small_task",
        profile="local_language",
        inputs=[f"What is {left} plus {right}?" for left, right in ((9, 4), (18, 7), (44, 12), (63, 19), (101, 22), (8, 35), (17, 81), (54, 46))],
    )
    _add(
        cases,
        family="small-arithmetic-validation",
        split="validation",
        route="small_task",
        profile="local_language",
        inputs=[f"Calculate {left} minus {right}." for left, right in ((20, 3), (91, 17), (45, 8), (100, 64))],
    )

    languages = ["French", "German", "Japanese", "Spanish", "Korean", "Italian", "Portuguese", "Dutch"]
    _add(
        cases,
        family="small-translation-train",
        split="train",
        route="small_task",
        profile="local_language",
        inputs=[f"Translate good morning into {language}." for language in languages[:6]],
    )
    _add(
        cases,
        family="small-translation-test",
        split="test",
        route="small_task",
        profile="local_language",
        inputs=[f"Give the {language} translation of thank you." for language in languages[6:]],
    )
    _add(
        cases,
        family="small-formatting-train",
        split="train",
        route="small_task",
        profile="local_language",
        inputs=[
            "Rewrite READY FOR REVIEW in lowercase.",
            "Put these words in alphabetical order: pear apple orange.",
            "Return this title in title case: system health report.",
            "Shorten this sentence to five words: The service completed the scheduled task successfully.",
            "List Monday, Tuesday, and Wednesday as comma-separated values.",
            "Change the sentence to past tense: The worker checks the file.",
        ],
    )

    abstract_train = [
        "freedom", "identity", "truth", "justice", "dignity", "sovereignty",
        "autonomy", "responsibility", "meaning", "consciousness", "morality",
        "trust", "power", "memory", "existence", "entropy",
    ]
    abstract_test = ["hope", "courage", "beauty", "obedience", "resistance", "civilization"]
    _add(
        cases,
        family="abstract-definition-train",
        split="train",
        route="deep_reasoning",
        profile="deep_reasoning",
        inputs=[f"What is {concept}?" for concept in abstract_train],
    )
    _add(
        cases,
        family="abstract-definition-test",
        split="test",
        route="deep_reasoning",
        profile="deep_reasoning",
        inputs=[f"Define {concept} as an abstract concept." for concept in abstract_test],
    )
    _add(
        cases,
        family="abstract-relation-validation",
        split="validation",
        route="deep_reasoning",
        profile="deep_reasoning",
        inputs=[
            "Compare freedom and responsibility.",
            "Explain how identity relates to memory.",
            "Analyse the relationship between sovereignty and power.",
            "How do truth and trust interact?",
            "Compare order and chaos.",
            "Explain why dignity matters to autonomy.",
        ],
    )
    _add(
        cases,
        family="deep-reasoning-train",
        split="train",
        route="deep_reasoning",
        profile="deep_reasoning",
        inputs=[
            "Compare two strategies for reducing model-call cost without losing reliability.",
            "Analyse the causal risks of automatic tool installation.",
            "Evaluate whether a small model should be allowed to make safety decisions.",
            "Compare deterministic routing with a learned controller.",
            "Analyse failure recovery for a multi-stage agent pipeline.",
            "Evaluate the market value of an auditable AI harness.",
            "Compare two governance designs for autonomous software agents.",
            "Analyse the long-term risks of hidden execution authority.",
        ],
    )
    _add(
        cases,
        family="deep-reasoning-test",
        split="test",
        route="deep_reasoning",
        profile="deep_reasoning",
        inputs=[
            "Assess the tradeoffs between speed, cost, and auditability in an AI operating system.",
            "Reason about how a system can preserve identity while changing its tools.",
            "Evaluate the consequences of allowing a controller to override deterministic safety gates.",
            "Compare centralised and distributed authority in a tool-using agent.",
        ],
    )

    code_languages = ["Python", "TypeScript", "JavaScript", "PowerShell", "SQL", "Go", "Rust", "Java", "C#", "C++"]
    _add(
        cases,
        family="code-fix-train",
        split="train",
        route="code_task",
        profile="code_coworker",
        inputs=[f"Fix a bug in this {language} code and add a regression test." for language in code_languages[:7]],
    )
    _add(
        cases,
        family="code-fix-test",
        split="test",
        route="code_task",
        profile="code_coworker",
        inputs=[f"Debug the failing {language} implementation." for language in code_languages[7:]],
    )
    _add(
        cases,
        family="code-refactor-validation",
        split="validation",
        route="code_task",
        profile="code_coworker",
        inputs=[
            "Refactor the API client and update its tests.",
            "Fix the timeout error in the backend service.",
            "Add pytest coverage for the JSON parser.",
            "Debug the CSS layout issue.",
        ],
    )

    _add(
        cases,
        family="tool-operation-train",
        split="train",
        route="tool_task",
        profile="auto",
        inputs=[
            "Open browser and inspect the current page.",
            "Take a screenshot of the desktop.",
            "Open the local file and read it.",
            "Search the folder for the report.",
            "Click the submit button in the browser.",
            "Use the tool to inspect the running process.",
            "Open the settings window.",
            "Show the contents of the local folder.",
        ],
    )
    _add(
        cases,
        family="tool-operation-test",
        split="test",
        route="tool_task",
        profile="auto",
        inputs=[
            "Capture a screenshot and inspect the visible error.",
            "Open browser, click the menu, and read the page.",
            "Find the local file in the folder.",
            "Use a tool to check the desktop window.",
        ],
    )
    _add(
        cases,
        family="tool-windows-validation",
        split="validation",
        route="tool_task",
        profile="windows_copilot",
        inputs=[
            "Use Windows Copilot to inspect the taskbar.",
            "Ask Copilot to check the Windows settings window.",
            "Use Windows Copilot to find a local file.",
            "Ask Copilot to inspect the Start menu.",
        ],
    )

    dates_train = ["2024-01-01", "2024-06-06", "2025-02-14", "2025-08-20", "2026-01-15", "2026-05-01"]
    dates_test = ["2023-03-08", "2024-11-11", "2025-12-25", "2026-04-04"]
    _add(
        cases,
        family="world-events-train",
        split="train",
        route="world_query",
        profile="api_reasoning",
        inputs=[f"world events on {date}" for date in dates_train],
    )
    _add(
        cases,
        family="world-events-test",
        split="test",
        route="world_query",
        profile="api_reasoning",
        inputs=[f"What happened in world history on {date}?" for date in dates_test],
    )
    _add(
        cases,
        family="world-news-validation",
        split="validation",
        route="world_query",
        profile="api_reasoning",
        inputs=[f"news on {date}" for date in ("2024-02-02", "2025-07-07", "2026-02-20")],
    )

    upgrade_components = [
        "benchmark", "harness", "prompt regression", "episode compare",
        "upgrade report", "tool registry", "runtime audit", "stability check",
    ]
    _add(
        cases,
        family="self-upgrade-train",
        split="train",
        route="self_upgrade",
        profile="upgrade",
        inputs=[f"Run the self-upgrade {component}." for component in upgrade_components[:6]],
    )
    _add(
        cases,
        family="self-upgrade-test",
        split="test",
        route="self_upgrade",
        profile="upgrade",
        inputs=[f"Check the {component} before self-upgrade." for component in upgrade_components[6:]],
    )

    for mode, split in (
        ("firewall", "train"),
        ("blackbox", "train"),
        ("scr", "train"),
        ("news", "validation"),
        ("sovereign", "validation"),
        ("tool_workshop", "test"),
        ("app_relay", "test"),
        ("trinity_only", "test"),
    ):
        _add(
            cases,
            family=f"forced-{mode}-{split}",
            split=split,
            route="forced",
            profile="auto",
            inputs=[f"Process this request using forced mode {mode}."],
            pipeline_mode=mode,
        )

    _add(
        cases,
        family="kairos-known-date-test",
        split="test",
        route="deterministic_memory",
        profile="deterministic",
        inputs=[
            "Kairos 2026-03-08 happened what?",
            "What does Kairos remember about 2026-03-08?",
            "Find the Kairos memory for 2026-03-08.",
        ],
    )

    return cases
