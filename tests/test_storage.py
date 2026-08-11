from ficc_terminal.briefing import build_pitch
from ficc_terminal.storage import JournalStore


def test_pitch_journal_round_trip(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.db")
    pitch = build_pitch("Macro hedge fund", "US 2s10s steepener")
    pitch_id = store.save_pitch(pitch, "2026-08-11")
    frame = store.list_pitches()
    assert frame.iloc[0]["id"] == pitch_id
    assert frame.iloc[0]["trade"] == "US 2s10s steepener"
    store.review_pitch(
        pitch_id,
        status="Closed — thesis wrong",
        performance="-5 bp",
        maximum_adverse_move="-8 bp",
        catalyst_outcome="The expected catalyst did not occur.",
        thesis_review="I over-weighted supply and under-weighted growth risk.",
    )
    reviewed = store.list_pitches().iloc[0]
    assert reviewed["status"] == "Closed — thesis wrong"

