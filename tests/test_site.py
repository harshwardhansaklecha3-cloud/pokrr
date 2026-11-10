"""The public website: every page loads, has search-engine basics, and the
machine-readable files list every page."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from server import site
from server.app import app

client = TestClient(app)
BASE = "http://testserver"          # the address the test client uses


@pytest.mark.parametrize("path", list(site.PAGES))
def test_page_has_seo_basics(path):
    r = client.get(path)
    assert r.status_code == 200
    html = r.text
    assert re.search(r"<title>[^<]{10,}</title>", html)
    desc = re.search(r'<meta name="description" content="([^"]+)"', html).group(1)
    assert 50 <= len(desc) <= 320
    assert f'<link rel="canonical" href="{BASE}{path}">' in html
    assert html.count("<h1>") == 1
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        json.loads(block)                                   # valid structured data
    assert 'href="/play"' in html                           # always one tap from the game


def test_every_page_is_in_the_sitemap_and_llms_txt():
    sm = client.get("/sitemap.xml").text
    llms = client.get("/llms.txt").text
    for path in site.PAGES:
        assert f"<loc>{BASE}{path}</loc>" in sm
        if path.startswith("/games/") or path.startswith("/learn/"):
            assert f"{BASE}{path}" in llms
    assert "Sitemap:" in client.get("/robots.txt").text
    full = client.get("/llms-full.txt").text
    assert "Royal flush" in full and "Trail" in full and "Elevator floors" in full


def test_game_moved_to_play_and_old_invites_redirect():
    assert 'id="lobby"' in client.get("/play").text
    r = client.get("/?room=K7QXM", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/play?room=K7QXM"
    assert client.get("/no-such-page").status_code == 404


def test_game_pages_list_fitting_addons():
    html = client.get("/games/floors").text
    assert "Not with this game:</b>" in html and "Deuces wild" in html
    yes, no = site.fitting_addons("classic")
    assert "Dice" in yes and "Deuces wild" in yes


def test_links_use_the_address_the_site_is_opened_on():
    html = TestClient(app, base_url="https://pokrr.example").get("/about").text
    assert '<link rel="canonical" href="https://pokrr.example/about">' in html
    assert "testserver" not in html
