from typing import Literal
from pydantic import BaseModel,Field,ConfigDict
class ErrataItem(BaseModel):
    model_config=ConfigDict(extra="forbid")
    code:str=Field(min_length=1,max_length=64)
    source_version:int=Field(ge=1,le=2147483647,strict=True)
    split:Literal['train','cal','test']
    values:dict
class ErrataImport(BaseModel):
    model_config=ConfigDict(extra="forbid")
    batch_no:str=Field(min_length=1,max_length=64)
    items:list[ErrataItem]=Field(min_length=1,max_length=2000)
class ErrataDetail(BaseModel):
    code:str
    source_version:int
    result:Literal['applied','skipped','rejected']
    reason:str=""
class ErrataBatchOutput(BaseModel):
    id:int
    study_id:int
    batch_no:str
    source_version:int
    status:Literal['applied','rejected']
    total:int
    applied:int
    skipped:int
    rejected:int
    details:list[ErrataDetail]
    error:str
    actor:str
    created_at:str
class WindowOutput(BaseModel):
    id:int
    study_id:int
    code:str
    split:Literal['train','cal','test']
    values:dict
    note:str
    source_version:int
    last_batch_id:int|None=None
class WindowAnnotation(BaseModel):
    note:str=Field(min_length=8,max_length=1500)
