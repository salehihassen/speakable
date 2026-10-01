from fastapi.testclient import TestClient

from speakable.app import app


def test_plain_text_api():
    with TestClient(app) as client:
        response = client.post("/api/v1/convert", json={"text": "**Hello** -> world", "use_llm": False})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello to world"


def test_details_api():
    with TestClient(app) as client:
        response = client.post("/api/v1/convert/details", json={"text": "Hello", "use_llm": False})
    assert response.json() == {"text": "Hello", "used_llm": False, "block_count": 0, "warnings": []}


def test_rejects_oversized_body_before_parsing():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/convert",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "262145"},
        )
    assert response.status_code == 413
