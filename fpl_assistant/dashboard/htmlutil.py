"""Renders raw HTML through st.markdown safely.

CommonMark (what Streamlit's markdown renderer uses) treats any line
indented 4+ spaces as a literal code block, not something to parse as
HTML. Every HTML template in this app (pitch.py, cards.py, styles.py) is
built from indented Python f-strings for readability, so passed directly
to st.markdown they render as visible raw HTML text instead of an actual
page. Stripping each line's leading whitespace before rendering sidesteps
that entirely — whitespace has no visual meaning in HTML/CSS anyway.
"""
import streamlit as st


def render_html(html: str) -> None:
    flattened = "\n".join(line.lstrip() for line in html.strip().split("\n"))
    st.markdown(flattened, unsafe_allow_html=True)
