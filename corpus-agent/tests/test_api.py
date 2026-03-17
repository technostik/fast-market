from __future__ import annotations


def test_sources(api_client):
    resp = api_client.get("/sources")
    assert resp.status_code == 200
    sources = resp.json()
    assert "obsidian" in sources
    assert "youtube" in sources


def test_sync_obsidian(api_client):
    resp = api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "obsidian"
    assert "indexed" in data


def test_sync_unknown_source(api_client):
    resp = api_client.post("/sync", json={"source": "nonexistent"})
    assert resp.status_code == 400


def test_items_empty(api_client):
    resp = api_client.get("/items?limit=50")
    assert resp.status_code == 200
    assert resp.json() == []


def test_items_after_sync(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    resp = api_client.get("/items?limit=50")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert all("title" in item for item in items)


def test_search_keyword(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    resp = api_client.get("/search?q=hello&mode=keyword&limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_search_bad_mode(api_client):
    resp = api_client.get("/search?q=hello&mode=invalid")
    assert resp.status_code == 400


def test_get_document(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    items = api_client.get("/items?limit=10").json()
    assert items
    doc = items[0]
    resp = api_client.get(f"/document/{doc['source_plugin']}/{doc['source_id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == doc["title"]


def test_get_document_not_found(api_client):
    assert api_client.get("/document/obsidian/nonexistent.md").status_code == 404


def test_delete_document(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    items = api_client.get("/items?limit=10").json()
    doc = items[0]
    assert api_client.delete(f"/document/{doc['source_plugin']}/{doc['source_id']}").status_code == 200
    assert api_client.get(f"/document/{doc['source_plugin']}/{doc['source_id']}").status_code == 404


def test_delete_document_not_found(api_client):
    assert api_client.delete("/document/obsidian/ghost.md").status_code == 404


def test_reindex(api_client):
    api_client.post("/sync", json={"source": "obsidian", "mode": "new", "limit": 10})
    resp = api_client.post("/reindex", json={"source": "obsidian"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "obsidian"
    assert data["documents"] >= 1


def test_frontend_fragments(api_client):
    resp = api_client.get("/api/frontend-fragments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_ui_home(api_client):
    resp = api_client.get("/ui", follow_redirects=True)
    assert resp.status_code == 200
    assert "corpus-agent" in resp.text


def test_ui_search_page(api_client):
    assert api_client.get("/ui/search").status_code == 200


def test_ui_items_page(api_client):
    assert api_client.get("/ui/items").status_code == 200


def test_ui_status_page(api_client):
    assert api_client.get("/ui/status").status_code == 200
