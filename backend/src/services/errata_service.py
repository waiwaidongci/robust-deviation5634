import math
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from ..models import ClimateWindow,FeatureSpec,WindowErrataBatch
from ..utils.serialize import record
from .study_service import get_study
from .audit_service import log
from ..config.database import study_lock

MAX_ABS=1e9

def list_batches(db,sid):
    get_study(db,sid)
    rows=db.query(WindowErrataBatch).filter_by(study_id=sid).order_by(WindowErrataBatch.id.desc())
    return [record(r) for r in rows]

def _feature_codes(db,sid):
    feats=db.query(FeatureSpec).filter_by(study_id=sid).order_by(FeatureSpec.position).all()
    return [f.code for f in feats],feats

def _finite_number(v):
    # 布尔在Python是int子类，显式拒绝；复数、NaN、Inf、非数值均拒绝
    if isinstance(v,bool) or not isinstance(v,(int,float)) or isinstance(v,complex):
        return False
    return math.isfinite(v) and abs(v)<=MAX_ABS

def import_errata(db,sid,data,user):
    get_study(db,sid)
    try:
        with study_lock(db,sid):
            return _import_locked(db,sid,data,user)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        # 并发下唯一约束（研究+批次号）兜底：冲突方整批放弃
        db.rollback()
        raise HTTPException(409,f"批次号 {data.batch_no} 并发冲突，整批未写入，请核对后重试")
    except Exception:
        db.rollback()
        raise

def _import_locked(db,sid,data,user):
    codes,feats=_feature_codes(db,sid)
    code_set=set(codes)
    if len(feats)!=4 or len(code_set)!=4:
        raise HTTPException(422,"该研究缺少固定四量口径，无法受理勘误")
    items=data.items
    # 批内编号不得重复，整批视为坏数据
    seen=set()
    for it in items:
        if it.code in seen:
            raise HTTPException(422,f"批内窗口编号重复：{it.code}，整批拒绝")
        seen.add(it.code)
    # 批次号在同一研究内唯一（乱序/重复回放可识别）
    dup_no=db.query(WindowErrataBatch).filter_by(study_id=sid,batch_no=data.batch_no).first()
    if dup_no:
        raise HTTPException(409,f"批次号 {data.batch_no} 已受理，请勿重复导入")
    # 批次来源版本取批内最高声明版本，仅用于批次记录展示；逐条按各自窗口版本判定
    batch_version=max(it.source_version for it in items)
    window_map={w.code:w for w in db.query(ClimateWindow).filter_by(study_id=sid).all()}
    details=[]
    applied=skipped=rejected=0
    # 先逐条全量校验，任何一条坏数据/冲突都不留下半批
    for it in items:
        reason=""
        if set(it.values.keys())!=code_set:
            reason="勘误值必须完整包含预定义4量且不得增减字段"
        elif not all(_finite_number(v) for v in it.values.values()):
            reason="存在非有限数值、布尔/复数或绝对值超过1e9的坏数据"
        else:
            win=window_map.get(it.code)
            if win is None:
                reason=f"窗口 {it.code} 不属于该研究，勘误必须针对既有窗口"
            elif it.split!=win.split:
                reason=f"角色由 {win.split} 变为 {it.split}，角色变化整批拒绝"
            elif it.source_version==win.source_version:
                same=all(float(it.values[c])==float(win.values[c]) for c in codes)
                if not same:
                    reason=f"同版（v{it.source_version}）异值，拒绝覆盖，整批拒绝"
                # 同版同值：幂等回放，跳过；旧版本回放也跳过（不回退）
            # source_version 更高且无冲突：进入应用候选
        if reason:
            rejected+=1
            details.append({"code":it.code,"source_version":it.source_version,"result":"rejected","reason":reason})
        else:
            win=window_map[it.code]
            if it.source_version<=win.source_version:
                skipped+=1
                why="旧批次回放，来源版本不新，保持现值不回退" if it.source_version<win.source_version else "同版同值回放，保持现值不回退"
                details.append({"code":it.code,"source_version":it.source_version,"result":"skipped","reason":why})
            else:
                details.append({"code":it.code,"source_version":it.source_version,"result":"applied","reason":""})
    if rejected:
        # 整批拒绝：不落任何窗口变更，仅留拒绝记录便于来源页展示处理结果
        row=WindowErrataBatch(study_id=sid,batch_no=data.batch_no,source_version=batch_version,
            status="rejected",total=len(items),applied=0,skipped=skipped,rejected=rejected,
            details=details,error="批内含坏数据或冲突，整批拒绝，未写入任何窗口",actor=user.email)
        db.add(row);db.flush()
        log(db,user.email,"errata.reject",row.id)
        db.commit()
        return record(row)
    # 全批通过：一次性应用，外部只能观察到完整一批
    row=WindowErrataBatch(study_id=sid,batch_no=data.batch_no,source_version=batch_version,
        status="applied",total=len(items),applied=0,skipped=skipped,rejected=0,
        details=details,error="",actor=user.email)
    db.add(row);db.flush()
    for it in items:
        win=window_map[it.code]
        if it.source_version>win.source_version:
            win.values={c:float(it.values[c]) for c in codes}
            win.source_version=it.source_version
            win.last_batch_id=row.id
            applied+=1
    row.applied=applied
    log(db,user.email,"errata.import",row.id)
    db.commit()
    return record(row)
