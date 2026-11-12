from fastapi.testclient import TestClient
from src.main import app
from src.config.database import SessionLocal
from src.models import WindowErrataBatch, ClimateWindow, ArchiveStudy
from tests.conftest import FEATURES

client = TestClient(app)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def payload(batch_no, items):
    return {"batch_no": batch_no, "items": items}


def test_unauthenticated_rejected(db, ids):
    r = client.get(f"/studies/{ids['study_id']}/errata")
    assert r.status_code == 401
    r = client.post(f"/studies/{ids['study_id']}/errata",
                    json=payload("X", []))
    assert r.status_code == 401


def test_viewer_cannot_import_but_can_read(db, ids):
    sid = ids["study_id"]
    body = payload("B-V", [{"code": "SL-T-W001", "source_version": 1, "split": "train",
                            "values": {c: 1.0 for c, *_ in FEATURES}}])
    r = client.post(f"/studies/{ids['study_id']}/errata", json=body,
                    headers=auth(ids["viewer_token"]))
    assert r.status_code == 403
    r = client.get(f"/studies/{sid}/errata", headers=auth(ids["viewer_token"]))
    assert r.status_code == 200 and r.json() == []


def test_analyst_import_full_http_flow(db, ids):
    sid = ids["study_id"]
    body = payload("B-HTTP-1", [
        {"code": "SL-T-W001", "source_version": 1, "split": "train",
         "values": {c: 12.5 for c, *_ in FEATURES}},
        {"code": "SL-T-W026", "source_version": 1, "split": "test",
         "values": {c: 3.25 for c, *_ in FEATURES}},
    ])
    r = client.post(f"/studies/{sid}/errata", json=body, headers=auth(ids["analyst_token"]))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "applied" and out["applied"] == 2
    # 窗口读模型带出来源版本
    rw = client.get(f"/studies/{sid}/windows", headers=auth(ids["analyst_token"])).json()
    w1 = next(w for w in rw if w["code"] == "SL-T-W001")
    assert w1["source_version"] == 1 and w1["last_batch_id"] == out["id"]
    # 批次清单可查询
    lst = client.get(f"/studies/{sid}/errata", headers=auth(ids["analyst_token"])).json()
    assert len(lst) == 1 and lst[0]["batch_no"] == "B-HTTP-1"


def test_validation_error_422_shape(db, ids):
    sid = ids["study_id"]
    # 空 items / 缺字段 / 非法 split / 额外字段
    r = client.post(f"/studies/{sid}/errata", json=payload("B", []),
                    headers=auth(ids["analyst_token"]))
    assert r.status_code == 422
    bad = {"batch_no": "B", "items": [{"code": "SL-T-W001", "source_version": 1,
                                       "split": "bogus", "values": {}}]}
    r = client.post(f"/studies/{sid}/errata", json=bad, headers=auth(ids["analyst_token"]))
    assert r.status_code == 422
    extra = {"batch_no": "B", "items": [{"code": "SL-T-W001", "source_version": 1,
                                         "split": "train",
                                         "values": {c: 1.0 for c, *_ in FEATURES}, "x": 1}]}
    r = client.post(f"/studies/{sid}/errata", json=extra, headers=auth(ids["analyst_token"]))
    assert r.status_code == 422


def test_duplicate_batch_no_409_and_bad_batch_rejected_via_http(db, ids):
    sid = ids["study_id"]
    good = {"code": "SL-T-W001", "source_version": 1, "split": "train",
            "values": {c: 1.0 for c, *_ in FEATURES}}
    r1 = client.post(f"/studies/{sid}/errata", json=payload("DUP", [good]),
                     headers=auth(ids["admin_token"]))
    assert r1.status_code == 201
    r2 = client.post(f"/studies/{sid}/errata", json=payload("DUP", [good]),
                     headers=auth(ids["admin_token"]))
    assert r2.status_code == 409
    # 角色变化整批拒绝（HTTP），且记录留在清单中
    role_bad = {"code": "SL-T-W001", "source_version": 2, "split": "cal",
                "values": {c: 2.0 for c, *_ in FEATURES}}
    r3 = client.post(f"/studies/{sid}/errata", json=payload("ROLE", [role_bad]),
                     headers=auth(ids["admin_token"]))
    assert r3.status_code == 201 and r3.json()["status"] == "rejected"
    s = SessionLocal()
    try:
        assert s.query(WindowErrataBatch).filter_by(study_id=sid).count() == 2
        w = s.query(ClimateWindow).filter_by(study_id=sid, code="SL-T-W001").one()
        assert w.split == "train" and w.source_version == 1  # 未被角色变更污染
    finally:
        s.close()


def test_errata_for_unknown_study_404(db, ids):
    r = client.get("/studies/99999/errata", headers=auth(ids["analyst_token"]))
    assert r.status_code == 404
    r = client.post("/studies/99999/errata",
                    json=payload("B", [{"code": "x", "source_version": 1, "split": "train",
                                        "values": {c: 1.0 for c, *_ in FEATURES}}]),
                    headers=auth(ids["analyst_token"]))
    assert r.status_code == 404
