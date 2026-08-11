from ficc_terminal.explanations import explain_us_rate_moves


def test_rate_move_explanation_defines_basis_points_and_avoids_claiming_cause() -> None:
    explanation = explain_us_rate_moves(
        two_year_level=4.06,
        two_year_change_bp=6,
        ten_year_level=4.27,
        ten_year_change_bp=7,
    )
    assert "0.01 percentage point" in explanation["number_meaning"]
    assert "4.00% to 4.06%" in explanation["number_meaning"]
    assert "do not prove" in explanation["possible_interpretation"]
    assert "TVC:US02Y" in explanation["how_to_verify"]
