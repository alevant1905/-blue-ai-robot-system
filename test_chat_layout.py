"""The chat page's message box and tool row (Alex, 2026-10-08: "make the text
window where i type larger. make sure it also fits well on my iphone").

The box used to share one row with ten buttons, which squeezed it to a sliver;
on the iPhone the phone rules sat at the TOP of the stylesheet, so the base
rules after them won and most of them never applied. These tests pin the
shape that fixed both.
"""

import re

from flask import Flask, render_template_string

from blue.server.pages.chat import CHAT_HTML


def render(kid):
    app = Flask("chat-layout-test")
    with app.app_context():
        return render_template_string(
            CHAT_HTML, kid=kid, hf_sens=5, robot_name="Blue", continuity_href="",
            robot_json='{"id":"blue","name":"Blue","head":"blue","accent":"#3da9fc"}',
        )


def _style(page):
    return page[page.index("<style>"):page.index("</style>")]


def test_the_box_has_its_own_row_above_the_tools():
    page = render(kid=False)
    card = page[page.index('<div class="input-card">'):page.index('<div class="input-bar">')]
    assert 'id="input"' in card, "the message box is back in the button row"
    assert page.count('id="input"') == 1


def test_the_box_size_comes_from_css_not_rows():
    """rows="3" set a floor that every smaller min-height (phone, landscape,
    kid) silently lost to."""
    page = render(kid=False)
    box = re.search(r'<textarea id="input"[^>]*>', page).group(0)
    assert 'rows="1"' in box
    assert 'enterkeyhint="send"' in box


def test_phone_rules_come_after_the_base_rules():
    """At the top of the sheet the phone block lost to the base rules after it."""
    style = _style(render(kid=False))
    phone = style.rindex("@media (max-width: 640px)")
    for base in ("#input {", ".input-bar {", ".sendbtn {", ".header {", ".navlinks {"):
        assert style.index(base) < phone, base


def test_phone_tools_fold_into_more_and_the_rest_stay_out():
    page = render(kid=False)
    bar = page[page.index('<div class="input-bar">'):page.index('id="sendBtn"')]
    more = bar[bar.index('id="toolsMore"'):]
    for tool in ("camBtn", "researchBtn", "wikiBtn", "contextBtn", "hfBtn", "voiceBtn", "speakBtn"):
        assert f'id="{tool}"' in more, tool
    for tool in ("attachBtn", "micBtn"):
        assert f'id="{tool}"' not in more, tool
    # "More" comes before the tray, so focus order reaches the tray after it.
    assert bar.index('id="moreBtn"') < bar.index('id="toolsMore"')


def test_vildas_box_stays_in_her_button_row():
    """She mostly talks: a box above the big mic row shrank her conversation
    to ~56px on the iPad held sideways."""
    page = render(kid=True)
    assert page.count('id="input"') == 1
    bar = page[page.index('<div class="input-bar">'):page.index('id="sendBtn"')]
    assert 'id="input"' in bar
    assert bar.index('id="micBtn"') < bar.index('id="input"')
