import {useEffect,useState} from 'react';
import {Upload,FileWarning,CheckCircle2,SkipForward,XCircle} from 'lucide-react';
import {useAuth} from '../stores/auth';
import {useAction} from '../hooks/useAction';
import {useResearch} from '../stores/research';
import {importErrata} from '../api/windows';
import {Notice} from './common/Notice';
import type {ErrataBatch,Study} from '../types/domain';

const RESULT_META={
  applied:{icon:CheckCircle2,label:'已取新值',cls:'ok'},
  skipped:{icon:SkipForward,label:'跳过不回退',cls:'muted'},
  rejected:{icon:XCircle,label:'整批拒绝',cls:'bad'},
} as const;

export function ErrataPanel({study}:{study:Study}){
  const {user}=useAuth();const a=useAction();const {errata,loadErrata,loadStudy}=useResearch();
  const [text,setText]=useState('');const [last,setLast]=useState<ErrataBatch|null>(null);
  const readOnly=user?.role==='viewer';
  useEffect(()=>{loadErrata(study.id)},[study.id,loadErrata]);
  async function submit(){
    let parsed:any;
    try{parsed=JSON.parse(text);}catch{throw new Error('JSON 解析失败，请检查格式');}
    if(!parsed||typeof parsed.batch_no!=='string'||!Array.isArray(parsed.items)){
      throw new Error('结构须为 {"batch_no":"…","items":[…]}');
    }
    const out=await importErrata(study.id,parsed);
    setLast(out);setText('');
    await Promise.all([loadErrata(study.id),loadStudy(study.id)]);
  }
  return <section className="errata-panel">
    <div className="section-heading"><h2>窗口勘误批次</h2><span>同窗口按来源版本取新值 · 旧批次不回退 · 冲突/坏数据整批拒绝</span></div>
    <Notice message={a.error} />
    {!readOnly&&<div className="errata-entry">
      <label>批次勘误 JSON<textarea aria-label="批次勘误JSON" value={text} onChange={e=>setText(e.target.value)} spellCheck={false}
        placeholder={'{\n  "batch_no": "202611-errata-03",\n  "items": [\n    {"code":"SL-01-W001","source_version":2,"split":"train",\n     "values":{"temperature":19.8,"humidity":46.2,"particles":17.1,"variation":0.31}}\n  ]\n}'}/></label>
      <div className="errata-actions">
        <button className="primary" disabled={a.busy||!text.trim()} onClick={()=>a.execute(submit)}><Upload size={15}/>导入批次</button>
        <small>整批先校验后写入；任一窗口坏数据、同版异值或角色变化，全批不留半批。</small>
      </div>
    </div>}
    {last&&<div className={'errata-result '+(last.status==='applied'?'ok':'bad')} role="status">
      <b><FileWarning size={16}/>批次 {last.batch_no}：{last.status==='applied'?'已受理':'整批拒绝'}</b>
      <p>共 {last.total} 条 · 取新值 {last.applied} · 跳过 {last.skipped} · 拒绝 {last.rejected}{last.error?` · ${last.error}`:''}</p>
    </div>}
    <div className="compact-table errata-table">
      <table>
        <thead><tr><th>批次号</th><th>来源版本</th><th>状态</th><th>取新/跳过/拒绝</th><th>处理明细</th><th>导入人</th></tr></thead>
        <tbody>{errata.length===0?<tr><td colSpan={6} className="empty">暂无勘误批次，来源窗口保持初始口径。</td></tr>:
          errata.map(b=><tr key={b.id} className={b.status==='rejected'?'row-bad':''}>
            <td>{b.batch_no}</td><td>v{b.source_version}</td>
            <td><span className={'review-badge '+b.status}>{b.status==='applied'?'已受理':'已拒绝'}</span></td>
            <td>{b.applied} / {b.skipped} / {b.rejected}</td>
            <td className="errata-details">{b.details.slice(0,4).map(d=>{const M=RESULT_META[d.result];const I=M.icon;
              return <span key={b.id+d.code} className={'detail-chip '+M.cls} title={d.reason||M.label}><I size={11}/>{d.code}·v{d.source_version}</span>;})}
              {b.details.length>4&&<small>等 {b.details.length} 条</small>}</td>
            <td>{b.actor}</td>
          </tr>)}</tbody>
      </table>
    </div>
  </section>;
}
