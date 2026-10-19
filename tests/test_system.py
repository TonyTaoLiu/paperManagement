from fastapi.testclient import TestClient
from papermind.main import create_app


def test_health_and_settings():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["fts5"] is True

    r = client.put(
        "/api/settings", json={"values": {"cloud_llm": {"api_key": "sk-x", "enabled": True}}}
    )
    assert r.json()["cloud_llm"]["api_key"] == "***"
    # masked placeholder must not overwrite the stored key
    client.put("/api/settings", json={"values": {"cloud_llm": {"api_key": "***", "model": "m"}}})
    from papermind.config import load_settings

    assert load_settings()["cloud_llm"]["api_key"] == "sk-x"
    assert load_settings()["cloud_llm"]["model"] == "m"
