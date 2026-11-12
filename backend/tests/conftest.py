import os, tempfile, pathlib
# 独立测试库，与任何真实数据隔离
_tmp = tempfile.mkdtemp(prefix="errata-tests-")
DB_PATH = pathlib.Path(_tmp) / "errata_test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{DB_PATH}")
os.environ.setdefault("REDIS_URL", "redis://localhost:6399/0")
os.environ.setdefault("JWT_SECRET", "errata-test-secret")
os.environ.setdefault("SEED_DEMO", "false")

import pytest
from sqlalchemy import event
from src.config.database import Base, engine, SessionLocal
from src.models import User, ArchiveStudy, FeatureSpec, ClimateWindow
from src.utils.security import hash_password, make_token

FEATURES = [
    ("temperature", "温度", "°C", 0),
    ("humidity", "相对湿度", "%RH", 1),
    ("particles", "颗粒浓度", "μg/m³", 2),
    ("variation", "温度波动", "°C", 3),
]

if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    admin = User(email="admin@shuangleng.demo", name="材料负责人", role="admin",
                 password_hash=hash_password("pw"))
    analyst = User(email="analyst@shuangleng.demo", name="研究员", role="analyst",
                   password_hash=hash_password("pw"))
    viewer = User(email="viewer@shuangleng.demo", name="阅读者", role="viewer",
                  password_hash=hash_password("pw"))
    session.add_all([admin, analyst, viewer])
    study = ArchiveStudy(code="SL-T", name="测试研究", description="d", source="test.csv",
                         default_alpha=0.05)
    session.add(study)
    session.flush()
    for code, label, unit, pos in FEATURES:
        session.add(FeatureSpec(study_id=study.id, code=code, label=label, unit=unit,
                                position=pos, meaning="m"))
    # 独立随机四量，保证训练矩阵满秩（避免合成线性导致秩亏）
    import numpy as np
    rng = np.random.default_rng(26026)
    X = rng.normal(size=(30, 4)) * np.array([1.5, 5.0, 4.0, 0.12]) + np.array([19.5, 47.0, 18.0, 0.35])
    for i in range(30):
        split = "train" if i < 20 else "cal" if i < 25 else "test"
        vals = {c: float(X[i, pos]) for c, _, _, pos in FEATURES}
        session.add(ClimateWindow(study_id=study.id, code=f"SL-T-W{i+1:03}", split=split,
                                  values=vals, note="seed"))
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def ids(db):
    study = db.query(ArchiveStudy).filter_by(code="SL-T").one()
    users = {u.role: u for u in db.query(User).all()}
    return {"study_id": study.id,
            "admin_token": make_token(users["admin"]),
            "analyst_token": make_token(users["analyst"]),
            "viewer_token": make_token(users["viewer"])}


def item(code, version, split, values=None):
    base = {c: 100.0 + version + pos for c, _, _, pos in FEATURES}
    if values is not None:
        base = values
    return {"code": code, "source_version": version, "split": split, "values": base}


def window(db, sid, code):
    return db.query(ClimateWindow).filter_by(study_id=sid, code=code).one()
