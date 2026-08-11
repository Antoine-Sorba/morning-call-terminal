from ficc_terminal.briefing import build_pitch
from ficc_terminal.feedback import evaluate_pitch


def test_template_placeholders_receive_actionable_feedback() -> None:
    pitch = build_pitch("Macro hedge fund", "US 2s10s steepener")
    pitch["catalyst"] = "No event selected"
    feedback = evaluate_pitch(pitch, event_selected=False)
    assert feedback["score"] < 75
    assert any("event" in message.lower() for message in feedback["improvements"])
    assert any("entry" in message.lower() or "market level" in message.lower() for message in feedback["improvements"])


def test_specific_pitch_passes_structural_checks() -> None:
    pitch = build_pitch("Macro hedge fund", "US 2s10s steepener")
    pitch.update(
        {
            "catalyst": "US inflation exceeded expectations in the official BLS release.",
            "entry_level": "Enter when the US 2s10s swap curve is -10 basis points.",
            "target": "Target a move to +5 basis points over six weeks.",
        }
    )
    feedback = evaluate_pitch(pitch, event_selected=True)
    assert feedback["score"] >= 85
    assert not feedback["improvements"]
