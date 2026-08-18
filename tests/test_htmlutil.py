"""Regression test for the Markdown-code-block bug: any line indented 4+
spaces gets rendered as a literal code block by Streamlit's markdown
renderer instead of being parsed as HTML. render_html() must neutralise
that on every line, no matter how deeply the source template was nested.
"""
from fpl_assistant.dashboard.htmlutil import render_html


def test_flattens_deeply_indented_html(monkeypatch):
    captured = {}

    def fake_markdown(text, unsafe_allow_html=False):
        captured["text"] = text
        captured["unsafe"] = unsafe_allow_html

    import fpl_assistant.dashboard.htmlutil as htmlutil

    monkeypatch.setattr(htmlutil.st, "markdown", fake_markdown)

    indented_html = """
    <div class="rank-card">
        <div class="rank-num">1</div>
            <div class="rank-info">Deeply nested</div>
    </div>
    """
    render_html(indented_html)

    for line in captured["text"].split("\n"):
        assert not line.startswith(" "), f"line still indented, would render as a code block: {line!r}"
    assert captured["unsafe"] is True
    assert "Deeply nested" in captured["text"]
