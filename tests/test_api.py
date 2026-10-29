import pytest
from fastapi.testclient import TestClient

import app as app_module
from blotto import service

client = TestClient(app_module.app)
CUSTOM = {"values": [1, 2, 3, 4, 5], "soldiers": 20, "payouts": [9, 4, 2, 0]}


def test_health_and_meta():
    assert client.get("/api/health").json() == {"ok": True}
    m = client.get("/api/meta").json()
    assert m["defaults"]["soldiers"] == 100 and "broad_mixture" in m["scenarios"]


def test_evaluate_custom_rules_small():
    r = client.post("/api/evaluate", json={"config": CUSTOM, "allocations": [[0, 2, 4, 6, 8], [4, 4, 4, 4, 4]],
                                           "pop_size": 400, "g2_groups": 2000, "custom_weights": {"equal": 1}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["g1"]["rows"]) == 2 and "custom" in d["g1"]["scenarios"]
    row = d["g2"]["rows"][0]
    assert abs(sum(row["pos"]["custom"]) - 1) < 1e-9


@pytest.mark.parametrize("payload, msg", [
    ({"allocations": [[20, 20, 20, 20, 21]]}, "sum to 100"),
    ({"allocations": [[20, 20, 20, 20]]}, "invalid allocation"),
    ({"config": {"soldiers": 1000}, "allocations": [[200] * 5]}, "soldiers must be"),
    ({"config": {"values": [1, 2, 3]}, "allocations": [[1, 1, 1]]}, "exactly 5 castles"),
])
def test_evaluate_rejects_bad_input(payload, msg):
    r = client.post("/api/evaluate", json=payload)
    assert r.status_code == 400 and msg in r.json()["detail"]


def test_non_json_body():
    r = client.post("/api/evaluate", content=b"nope", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_best_response_and_optimize_and_self_play_custom_rules():
    r = client.post("/api/best-response/g1", json={"config": CUSTOM, "target": "proportional", "pop_size": 400, "k": 5})
    assert r.status_code == 200, r.text
    assert len(r.json()["top"]) == 5 and sum(r.json()["top"][0]) == 20
    r = client.post("/api/optimize/g2", json={"config": CUSTOM, "target": "random", "pop_size": 400,
                                              "time_budget": 3, "groups": 1000})
    assert r.status_code == 200, r.text
    assert sum(r.json()["results"][0]["alloc"]) == 20
    r = client.post("/api/self-play", json={"config": CUSTOM, "game": "g1", "iters": 5, "pop_size": 300})
    assert r.status_code == 200 and len(r.json()["best_responses"]) == 5


def test_tournament():
    r = client.post("/api/tournament", json={"allocations": [[20] * 5, [0, 10, 20, 30, 40], [0, 0, 0, 50, 50],
                                                             [7, 13, 20, 27, 33]]})
    d = r.json()
    assert r.status_code == 200 and len(d["g2"]["rows"]) == 4
    assert abs(sum(x["mean"] for x in d["g2"]["rows"]) - 15) < 1e-9


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
