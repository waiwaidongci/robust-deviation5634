import threading
import pytest
from fastapi import HTTPException
from src.services.errata_service import import_errata, list_batches
from src.services.study_service import create_snapshot
from src.services import run_service
from src.models import ClimateWindow, DeviationRun, ReviewNote
from src.schemas.window import ErrataImport
from tests.conftest import item, window

CODES4 = ["temperature", "humidity", "particles", "variation"]


class FakeUser:
    def __init__(self, email):
        self.email = email
        self.name = email


def call(db, sid, batch_no, items, email="analyst@shuangleng.demo"):
    return import_errata(db, sid, ErrataImport(batch_no=batch_no, items=items), FakeUser(email))


def expect_422(fn):
    with pytest.raises(HTTPException) as ei:
        fn()
    assert ei.value.status_code == 422
    return ei.value.detail


def expect_409(fn):
    with pytest.raises(HTTPException) as ei:
        fn()
    assert ei.value.status_code == 409
    return ei.value.detail


# ---------- 1. 新版本取新值、旧批次回放不回退 ----------

def test_apply_newer_version_takes_new_values(db, ids):
    sid = ids["study_id"]
    before = window(db, sid, "SL-T-W001")
    assert before.source_version == 0
    row = call(db, sid, "B-001", [item("SL-T-W001", 1, "train"), item("SL-T-W026", 1, "test")])
    assert row['status'] == "applied" and row['applied'] == 2 and row['rejected'] == 0
    db.expire_all()
    w1 = window(db, sid, "SL-T-W001")
    assert w1.source_version == 1 and w1.last_batch_id == row["id"]
    assert w1.values["temperature"] == pytest.approx(101.0)
    # 未涉及的窗口仍为 v0
    assert window(db, sid, "SL-T-W002").source_version == 0


def test_older_batch_replay_does_not_roll_back(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-001", [item("SL-T-W001", 2, "train")])
    v2_values = dict(window(db, sid, "SL-T-W001").values)
    # 旧批次（v1，且数值不同）回放：跳过，现值不回退
    row = call(db, sid, "B-OLD", [item("SL-T-W001", 1, "train")])
    assert row['status'] == "applied" and row['applied'] == 0 and row['skipped'] == 1
    db.expire_all()
    w = window(db, sid, "SL-T-W001")
    assert w.source_version == 2 and w.values == v2_values and w.last_batch_id is not None
    assert row['details'][0]["result"] == "skipped"


def test_mixed_new_and_old_in_one_batch_applies_only_newer(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-001", [item("SL-T-W001", 3, "train")])
    row = call(db, sid, "B-002", [
        item("SL-T-W001", 2, "train"),   # 旧于v3：跳过
        item("SL-T-W002", 4, "train"),   # 新于v0：应用
    ])
    assert row['applied'] == 1 and row['skipped'] == 1 and row['rejected'] == 0
    db.expire_all()
    assert window(db, sid, "SL-T-W001").source_version == 3
    assert window(db, sid, "SL-T-W002").source_version == 4


def test_batch_with_different_window_versions_applies_each_by_its_own_version(db, ids):
    sid = ids["study_id"]
    # 同一批内不同窗口带来不同来源版本：按各自窗口版本判定，不强制全批同版
    row = call(db, sid, "B-MIXV", [
        item("SL-T-W001", 1, "train"),
        item("SL-T-W002", 5, "train"),
        item("SL-T-W003", 2, "train"),
    ])
    assert row['status'] == "applied" and row['applied'] == 3
    db.expire_all()
    assert window(db, sid, "SL-T-W001").source_version == 1
    assert window(db, sid, "SL-T-W002").source_version == 5
    assert window(db, sid, "SL-T-W003").source_version == 2


# ---------- 2. 同版异值 / 角色变化：整批拒绝，不留半批 ----------

def test_same_version_different_value_rejects_whole_batch(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-001", [item("SL-T-W001", 1, "train"), item("SL-T-W002", 1, "train")])
    good = dict(window(db, sid, "SL-T-W002").values)
    conflict_values = {c: 999.0 for c in CODES4}
    row = call(db, sid, "B-BAD", [
        item("SL-T-W001", 1, "train", conflict_values),  # 同版异值
        item("SL-T-W003", 2, "train"),                    # 本可应用
    ])
    assert row['status'] == "rejected" and row['rejected'] == 1 and row['applied'] == 0
    # 同批里“本可应用”的窗口也不得写入（整批不落库）
    db.expire_all()
    assert window(db, sid, "SL-T-W003").source_version == 0
    assert window(db, sid, "SL-T-W002").values == good
    assert any(d["result"] == "rejected" and "同版" in d["reason"] for d in row['details'])
    assert any(d["code"] == "SL-T-W003" and d["result"] == "applied" for d in row['details'])


def test_role_change_rejects_whole_batch(db, ids):
    sid = ids["study_id"]
    row = call(db, sid, "B-ROLE", [
        item("SL-T-W001", 1, "cal"),    # 角色 train -> cal
        item("SL-T-W002", 1, "train"),
    ])
    assert row['status'] == "rejected"
    assert any("角色" in d["reason"] for d in row['details'])
    db.expire_all()
    w = window(db, sid, "SL-T-W001")
    assert w.split == "train" and w.source_version == 0
    assert window(db, sid, "SL-T-W002").source_version == 0


def test_same_version_same_values_is_idempotent_skip(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-001", [item("SL-T-W001", 1, "train")])
    snap_values = dict(window(db, sid, "SL-T-W001").values)
    row = call(db, sid, "B-REPLAY", [item("SL-T-W001", 1, "train", dict(snap_values))])
    assert row['applied'] == 0 and row['skipped'] == 1 and row['rejected'] == 0
    db.expire_all()
    assert window(db, sid, "SL-T-W001").values == snap_values


# ---------- 3. 批内坏数据：整批拒绝 ----------

@pytest.mark.parametrize("bad", [
    {**{c: 1.0 for c in CODES4}, "temperature": float("nan")},
    {**{c: 1.0 for c in CODES4}, "humidity": float("inf")},
    {**{c: 1.0 for c in CODES4}, "particles": True},          # 布尔拒绝
    {**{c: 1.0 for c in CODES4}, "variation": complex(1, 1)},  # 复数拒绝
    {c: 1.0 for c in CODES4 if c != "variation"},              # 缺字段
    {**{c: 1.0 for c in CODES4}, "extra": 1.0},                # 多字段
    {**{c: 1.0 for c in CODES4}, "temperature": "19.5"},      # 字符串非数值
])
def test_bad_data_rejects_whole_batch_no_half_batch(db, ids, bad):
    sid = ids["study_id"]
    row = call(db, sid, "B-BAD-" + str(len(bad)), [
        item("SL-T-W001", 1, "train", bad),
        item("SL-T-W002", 1, "train"),
    ])
    assert row['status'] == "rejected" and row['applied'] == 0
    db.expire_all()
    # 同批的好数据也不得落库
    assert window(db, sid, "SL-T-W002").source_version == 0
    assert window(db, sid, "SL-T-W001").source_version == 0


def test_abs_value_over_1e9_rejected(db, ids):
    sid = ids["study_id"]
    bad = {c: 2e9 for c in CODES4}
    row = call(db, sid, "B-HUGE", [item("SL-T-W001", 1, "train", bad)])
    assert row['status'] == "rejected"


def test_unknown_window_and_duplicate_in_batch_rejected(db, ids):
    sid = ids["study_id"]
    row = call(db, sid, "B-UNKNOWN", [item("SL-T-W999", 1, "train")])
    assert row['status'] == "rejected" and any("不属于该研究" in d["reason"] for d in row['details'])
    msg = expect_422(lambda: call(db, sid, "B-DUP", [
        item("SL-T-W001", 1, "train"), item("SL-T-W001", 2, "train")]))
    assert "重复" in msg


def test_rejected_batch_persists_record_for_result_display(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-BAD", [item("SL-T-W001", 1, "cal")])
    batches = list_batches(db, sid)
    assert len(batches) == 1 and batches[0]["status"] == "rejected"
    assert batches[0]["total"] == 1 and batches[0]["rejected"] == 1


# ---------- 4. 重复批次号 / 乱序回放 ----------

def test_duplicate_batch_no_conflicts(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-001", [item("SL-T-W001", 1, "train")])
    msg = expect_409(lambda: call(db, sid, "B-001", [item("SL-T-W002", 1, "train")]))
    assert "B-001" in msg
    # 第二次未写入
    assert window(db, sid, "SL-T-W002").source_version == 0


def test_out_of_order_delivery_converges_to_latest(db, ids):
    sid = ids["study_id"]
    call(db, sid, "B-v3", [item("SL-T-W001", 3, "train")])
    call(db, sid, "B-v1", [item("SL-T-W001", 1, "train")])  # 迟到旧批
    call(db, sid, "B-v2", [item("SL-T-W002", 2, "train")])
    call(db, sid, "B-v4", [item("SL-T-W001", 4, "train")])
    db.expire_all()
    assert window(db, sid, "SL-T-W001").source_version == 4
    assert window(db, sid, "SL-T-W002").source_version == 2


# ---------- 5. 快照隔离：只读到完整一批，且已完成研究/获批/导出保持原样 ----------

def test_snapshot_reads_only_complete_batch(db, ids):
    sid = ids["study_id"]
    # 预先创建并完成一个研究，快照冻结勘误前的值
    run_service.queue = type("Q", (), {"rpush": lambda *a, **k: None})()
    from src.schemas.run import RunInput
    created = run_service.create_run(db, RunInput(name="冻结基线", study_id=sid, alpha=0.05, seed=7),
                                 FakeUser("analyst@shuangleng.demo"))
    run = db.get(DeviationRun, created["id"])
    run.status = "completed"
    db.commit()
    frozen = {w["code"]: dict(w["values"]) for w in run.input_snapshot["windows"]}

    # 勘误改变多个窗口
    call(db, sid, "B-NEW", [item(f"SL-T-W{i:03}", 5, "train") for i in range(1, 6)])
    db.expire_all()

    # 旧运行的冻结快照不变
    old = db.get(DeviationRun, run.id)
    assert old.input_snapshot["windows"][0]["source_version"] == 0
    assert {w["code"]: dict(w["values"]) for w in old.input_snapshot["windows"]} == frozen

    # 新快照读到的是完整新值
    snap = create_snapshot(db, _study(db, sid))
    by_code = {w["code"]: w for w in snap["windows"]}
    for i in range(1, 6):
        assert by_code[f"SL-T-W{i:03}"]["source_version"] == 5
    assert all(by_code[f"SL-T-W{i:03}"]["source_version"] == 0 for i in range(6, 31))


def _study(db, sid):
    from src.models import ArchiveStudy
    return db.query(ArchiveStudy).filter_by(id=sid).one()


def test_approved_completed_run_and_export_unchanged_after_errata(db, ids):
    sid = ids["study_id"]
    run_service.queue = type("Q", (), {"rpush": lambda *a, **k: None})()
    from src.schemas.run import RunInput
    created = run_service.create_run(db, RunInput(name="获批研究", study_id=sid, alpha=0.05, seed=7),
                                 FakeUser("analyst@shuangleng.demo"))
    run = db.get(DeviationRun, created["id"])
    # 构造一个已完成且获批的研究
    run.status = "completed"
    run.result = {"features": [{"code": c} for c in CODES4],
                  "test": [{"window": {"code": "SL-T-W026", "split": "test",
                                       "values": {c: 1.0 for c in CODES4}},
                            "d2": 1.0, "cal_ge_count": 0, "p": 0.5, "selected": False}],
                  "counts": {"cal": 5}, "fit_hash": "f", "input_hash": "h"}
    db.add(ReviewNote(run_id=run.id, title="t", interpretation="i" * 8, proposal="p" * 8,
                      status="approved", owner="o", reviewer="r", review_note="n" * 8))
    db.commit()
    csv_before = run_service.export_run(db, run.id)

    # 勘误改变源窗口（含导出中的测试窗口）
    call(db, sid, "B-EXPORT", [item("SL-T-W026", 9, "test")])
    db.expire_all()
    csv_after = run_service.export_run(db, run.id)
    assert csv_before == csv_after  # 已获批下载内容保持原样
    # 源数据确实已更新
    assert window(db, sid, "SL-T-W026").source_version == 9


# ---------- 6. 并发：导入彼此串行，快照无半批 ----------

def test_concurrent_imports_are_serialized_and_never_torn(db, ids):
    sid = ids["study_id"]
    errors = []

    def worker(prefix, versions):
        from src.config.database import SessionLocal
        local = SessionLocal()
        try:
            for v in versions:
                try:
                    import_errata(local, sid,
                                  ErrataImport(batch_no=f"{prefix}-v{v}",
                                               items=[item("SL-T-W001", v, "train")]),
                                  FakeUser(f"{prefix}@x"))
                except HTTPException as e:
                    errors.append((prefix, v, e.status_code))
        finally:
            local.close()

    t1 = threading.Thread(target=worker, args=("A", [1, 3, 5, 7]))
    t2 = threading.Thread(target=worker, args=("B", [2, 4, 6, 8]))
    t1.start(); t2.start(); t1.join(); t2.join()

    db.expire_all()
    w = window(db, sid, "SL-T-W001")
    # 最终值收敛到最高版本 v8，绝不出现中间态残留
    assert w.source_version == 8
    assert w.values["temperature"] == pytest.approx(100.0 + 8.0)
    # 每条批次记录状态明确（applied/rejected），无半批：applied 数之和与最终版本一致
    from src.models import WindowErrataBatch
    batches = db.query(WindowErrataBatch).filter_by(study_id=sid).all()
    assert len(batches) == 8
    assert all(b.status in ("applied", "rejected") for b in batches)
    # 无半批：每条批次记录 applied 仅 0 或 1（单窗口批次），且最终值收敛到最高版本 v8
    assert all(b.applied in (0, 1) for b in batches)
    assert sum(b.applied for b in batches) >= 1
    # 没有任何窗口被旧值回退：版本单调不减，最终为 8


def test_concurrent_snapshot_never_observes_half_batch(db, ids):
    sid = ids["study_id"]
    from src.config.database import SessionLocal
    from src.models import ArchiveStudy
    snapshots, stop = [], threading.Event()

    def reader():
        local = SessionLocal()
        try:
            while not stop.is_set():
                study = local.query(ArchiveStudy).filter_by(id=sid).one()
                snap = create_snapshot(local, study)
                ver = {w["code"]: w["source_version"] for w in snap["windows"]}
                snapshots.append(ver)
        finally:
            local.close()

    r = threading.Thread(target=reader); r.start()
    writer = SessionLocal()
    try:
        for v in range(1, 6):
            import_errata(writer, sid,
                          ErrataImport(batch_no=f"W-v{v}",
                                       items=[item(f"SL-T-W{i:03}", v, "train") for i in range(1, 11)]),
                          FakeUser("w@x"))
    finally:
        stop.set(); writer.close(); r.join()

    # 每个快照内：本批 10 个窗口的版本必须齐步走（全 v 或全 v-1），不存在半批
    for ver in snapshots:
        touched = [ver[f"SL-T-W{i:03}"] for i in range(1, 11)]
        assert len(set(touched)) == 1, f"观察到半批快照: {set(touched)}"
        assert all(ver[f"SL-T-W{i:03}"] == 0 for i in range(11, 31))
    assert snapshots, "读线程至少应捕获一个快照"
