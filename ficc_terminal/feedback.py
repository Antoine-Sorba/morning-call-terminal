from __future__ import annotations


PLACEHOLDER_TEXT = (
    "complete after",
    "define using",
    "complete after choosing",
    "no event selected",
)


def _is_specific(value: str, minimum_words: int = 4) -> bool:
    lowered = value.strip().lower()
    return len(lowered.split()) >= minimum_words and not any(
        placeholder in lowered for placeholder in PLACEHOLDER_TEXT
    )


def evaluate_pitch(pitch: dict[str, str], *, event_selected: bool) -> dict[str, object]:
    """Give immediate feedback on pitch structure, never on expected returns."""

    checks = [
        (
            "Source-linked catalyst",
            event_selected and _is_specific(pitch.get("catalyst", ""), 5),
            "Choose one overnight event and describe why it could affect the market.",
        ),
        (
            "Clear market view",
            _is_specific(pitch.get("market_view", ""), 12),
            "Explain the direction, the mechanism and why the market may not have fully priced it.",
        ),
        (
            "Specific instrument",
            _is_specific(pitch.get("instrument", ""), 7),
            "Name the product, direction, maturity and structure rather than only the asset class.",
        ),
        (
            "Entry level",
            _is_specific(pitch.get("entry_level", ""), 2),
            "Add the latest checked market level and state its convention.",
        ),
        (
            "Target or hedge objective",
            _is_specific(pitch.get("target", ""), 4),
            "Define a measurable target or a precise hedging objective.",
        ),
        (
            "Invalidation",
            _is_specific(pitch.get("invalidation", ""), 8),
            "State the observable event or level that would make the thesis wrong.",
        ),
        (
            "Client relevance",
            _is_specific(pitch.get("client_relevance", ""), 12),
            "Connect the trade to the client's exposure, constraints and objective.",
        ),
        (
            "Risk and horizon",
            _is_specific(pitch.get("main_risk", ""), 8)
            and _is_specific(pitch.get("time_horizon", ""), 2),
            "State both the main risk and a realistic time horizon.",
        ),
    ]
    passed = [label for label, ok, _ in checks if ok]
    improvements = [message for _, ok, message in checks if not ok]
    score = round(len(passed) / len(checks) * 100)
    return {
        "score": score,
        "passed": passed,
        "improvements": improvements,
        "summary": (
            "Interview-ready structure" if score >= 85 else
            "Good foundation; make the missing elements specific" if score >= 60 else
            "The idea needs more evidence and trade detail"
        ),
    }

