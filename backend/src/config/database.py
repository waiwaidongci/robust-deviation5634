import threading
from contextlib import contextmanager
from sqlalchemy import create_engine,text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .settings import DATABASE_URL
class Base(DeclarativeBase):
    pass
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
# 研究级串行锁：窗口勘误导入与研究快照互斥，保证快照只读到完整批次
LOCK_KEY=730026
# SQLite（本地/测试）无事务咨询锁，用进程内研究级互斥；生产 PostgreSQL 用 pg_advisory_xact_lock
_thread_locks:dict[int,threading.RLock]={}
_locks_guard=threading.Lock()
@contextmanager
def study_lock(db,sid):
    if engine.dialect.name=="postgresql":
        # 事务级咨询锁：随 commit/rollback 自动释放，同一事务内可重入
        db.execute(text("SELECT pg_advisory_xact_lock(:k,:s)"),{"k":LOCK_KEY,"s":sid})
        yield
    else:
        with _locks_guard:
            lk=_thread_locks.get(sid)
            if lk is None:
                lk=threading.RLock();_thread_locks[sid]=lk
        lk.acquire()
        try:
            yield
        finally:
            lk.release()
def get_db():
    with SessionLocal() as db:
        yield db
