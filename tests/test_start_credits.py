"""Футер «сделано deepseek» в приветствии."""


def test_start_text_credits_deepseek():
    from app.render import render_main_menu

    text, _ = render_main_menu("severo_bot", "")
    assert "сделано deepseek" in text
    # подпись идёт последней строкой
    assert text.rstrip().endswith("сделано deepseek</i>")


def test_footer_present_with_app_buttons():
    from app.render import render_main_menu

    text, keyboard = render_main_menu("severo_bot", "https://example.com")
    assert "сделано deepseek" in text
    assert keyboard is not None
