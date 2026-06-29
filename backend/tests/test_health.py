import pytest
from main import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json["status"] == "ok"


def test_data_status_not_loaded(client):
    r = client.get("/api/data/status")
    assert r.status_code == 200
    assert r.json["loaded"] is False
