"""Cockpit v2 foundation: the site map (every rail entry renders, every retired URL redirects to a
page that renders), preview mode (banner, read-only guard, compare links) and the env URL overrides."""
import pytest
from fastapi.testclient import TestClient

import webauth
from cockpit import pages as main_pages
from cockpit_ops import pages as ops_pages


@pytest.fixture(scope="module")
def clients(tmp_path_factory):
    from cockpit.app import app as main
    from cockpit_ops.app import app as ops
    mp = pytest.MonkeyPatch()
    mp.setattr(webauth, "AUTH_FILE", tmp_path_factory.mktemp("auth") / "auth.json")
    webauth.set_password("correct horse battery")
    cookies = {webauth.COOKIE: webauth.make_token()}
    yield TestClient(main, cookies=cookies), TestClient(ops, cookies=cookies)
    mp.undo()
    from cockpit_ops import api       # rendering /flow memoised the live overview; later tests patch its inputs
    api.get_flow_overview.cache_clear()


@pytest.fixture(autouse=True)
def _live(monkeypatch):
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)


def test_every_rail_entry_renders(clients):
    main, ops = clients
    for client, pages in ((main, main_pages.PAGES), (ops, ops_pages.PAGES)):
        for p in pages:
            r = client.get(p["path"])
            assert r.status_code == 200, p["path"]


def test_site_map_order():
    assert [p["title"] for p in main_pages.PAGES] == ["Today", "Explorer", "Stocks", "Markets", "Sectors", "Investor Playbooks", "Book", "Model", "Funds"]
    assert [p["title"] for p in ops_pages.PAGES] == ["Health", "Feeds", "Flow", "Boardroom", "Options", "SQL"]
    for pages in (main_pages.PAGES, ops_pages.PAGES):                 # the bar holds at most 4 tabs
        assert sorted(p["mobile"] for p in pages if p.get("mobile")) == [1, 2, 3, 4]


def test_retired_urls_redirect_to_a_page_that_renders(clients):
    main, ops = clients
    expect = {"/actions": "/", "/explorer/REDY": "/stocks/REDY",
              "/news": "/markets", "/news/all": "/markets#search", "/multibagger": "/playbooks#strict",
              "/ideas": "/playbooks", "/portfolio": "/book", "/model/outcomes": "/book#track-record"}
    for old, new in expect.items():
        r = main.get(old, follow_redirects=False)
        assert r.status_code in (301, 302) and r.headers["location"] == new, old
        assert main.get(new.split("#")[0]).status_code in (200, 404), old     # 404 only for an unknown stock
    r = ops.get("/command", follow_redirects=False)
    assert r.status_code in (301, 302) and r.headers["location"] == "/system"
    assert ops.get("/command").status_code == 200


def test_every_redirect_in_the_registry_is_exercised(clients):
    main, ops = clients
    for client, pages in ((main, main_pages), (ops, ops_pages)):
        for old, _ in pages.REDIRECTS:
            r = client.get(old.format(sid="REDY", theme_id="oil_energy"), follow_redirects=False)
            assert r.status_code in (301, 302), old


def test_banner_only_in_preview(clients, monkeypatch):
    main, ops = clients
    for c in (main, ops):
        assert "preview-banner" not in c.get("/system" if c is ops else "/").text
    monkeypatch.setenv("COCKPIT_PREVIEW", "1")
    for c, path in ((main, "/"), (ops, "/system")):
        t = c.get(path).text
        assert "preview-banner" in t and "Open this page on the live cockpit" in t and "read-only" in t


def test_compare_links(clients, monkeypatch):
    import preview
    monkeypatch.setenv("COCKPIT_PREVIEW", "1")
    monkeypatch.setenv("COCKPIT_COMPARE_MAIN_URL", "http://live-main:3000/")
    monkeypatch.setenv("COCKPIT_COMPARE_OPS_URL", "https://live-ops")
    assert preview.compare_links("main", "/book")["url"] == "http://live-main:3000/portfolio"
    assert preview.compare_links("main", "/stocks/REDY")["url"] == "http://live-main:3000/explorer/REDY"
    assert preview.compare_links("main", "/markets")["tabs"]["#search"] == "http://live-main:3000/news/all"
    for same in ("/explorer", "/sectors", "/playbooks"):                    # restored pages: identity
        assert preview.compare_links("main", same)["url"] == f"http://live-main:3000{same}"
    assert preview.compare_links("main", "/playbooks")["tabs"]["#strict"] == "http://live-main:3000/multibagger"
    assert preview.compare_links("main", "/")["url"] == "http://live-main:3000/"
    assert preview.compare_links("main", "/mutual-funds/123")["url"] == "http://live-main:3000/mutual-funds/123"
    assert preview.compare_links("ops", "/flow")["tabs"]["#pipeline-log"] == "https://live-ops/system#pipeline"
    main, _ = clients
    assert 'href="http://live-main:3000/portfolio"' in main.get("/book").text


def test_readonly_guard(clients, monkeypatch):
    main, ops = clients
    # live: the guard does nothing (the route is reached: 404/405/422, never the preview 403)
    assert main.post("/api/search").status_code != 403
    monkeypatch.setenv("COCKPIT_PREVIEW", "1")
    for c, path in ((main, "/api/anything"), (ops, "/api/org/decide"), (ops, "/api/pipeline/rerun/x"), (ops, "/api/sql")):
        for method in ("post", "put", "delete", "patch"):
            r = getattr(c, method)(path)
            assert r.status_code == 403 and r.json() == {"error": "preview is read-only — use the live cockpit"}, (path, method)
    assert main.get("/api/search?q=ab").status_code == 200           # reads still work
    r = TestClient(main.app).post("/login", data={"password": "wrong"})  # the login POST is not blocked
    assert r.status_code == 401


def test_cross_cockpit_links_follow_env(clients, monkeypatch):
    main, ops = clients
    assert "preview-ops.example" not in main.get("/").text
    monkeypatch.setenv("COCKPIT_OPS_URL", "https://preview-ops.example/")
    monkeypatch.setenv("COCKPIT_MAIN_URL", "https://preview.example")
    assert 'href="https://preview-ops.example/system"' in main.get("/").text
    assert "https://preview.example" in ops.get("/system").text


def test_prewarm_can_be_skipped(monkeypatch):
    from cockpit import _shared
    monkeypatch.setenv("COCKPIT_NO_PREWARM", "1")
    called = []
    _shared.prewarm([("x", lambda: called.append(1))])
    import time; time.sleep(0.2)
    assert not called


def test_restored_pages_render_with_their_tabs(clients):
    main, _ = clients
    for path, tabs in (("/sectors", ["Today", "Industry Detail", "Rotation"]), ("/explorer", [])):
        t = main.get(path).text
        assert all(f">{x}</button>" in t for x in tabs), path
    assert main.get("/sectors?industry=Banks").status_code == 200
    assert "/stocks/" in main.get("/explorer").text and "/explorer/" not in main.get("/explorer").text.replace('href="/explorer"', "")
    assert 'href="/sectors"' in main.get("/markets").text and ">Industries" in main.get("/markets").text
    pb = main.get("/playbooks").text
    assert [k for k, _ in main_pages.PLAYBOOK_TABS][0] == "avoid" and pb.count('class="tab-button"') == len(main_pages.PLAYBOOK_TABS)
    for key, _label in main_pages.PLAYBOOK_TABS[1:]:
        assert main.get(f"/partial/playbooks/{key}").status_code == 200, key
    assert main.get("/partial/playbooks/nope").status_code == 404


def test_playbook_tabs_match_producers():
    from cockpit import playbooks
    assert [k for k, _ in main_pages.PLAYBOOK_TABS] == list(playbooks.TABS)


def test_industry_detail_tab_has_one_linked_tile_per_industry(clients):
    import re
    from urllib.parse import quote
    from cockpit import api
    main, _ = clients
    inds = api.get_industry_rotation()
    assert inds
    html = main.get("/sectors?industry=" + quote(inds[0]["industry"])).text
    tiles = re.findall(r'<a class="it-tile[^"]*"\s+href="([^"]+)"', html)
    assert len(tiles) == len(inds)
    for ind in inds:
        assert f'href="/sectors?industry={quote(ind["industry"])}#per-sector"' in html
        assert ind["industry"].replace("&", "&amp;") in html
        assert f'{ind["stocks"]} stocks' in html
    assert html.count('aria-current="true"') >= 1          # the opened industry's tile is marked
