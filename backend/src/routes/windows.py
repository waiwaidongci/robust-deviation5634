from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from ..config.database import get_db
from ..controllers.dependencies import current_user,roles
from ..constants.roles import Role
from ..schemas.window import WindowOutput,WindowAnnotation,ErrataImport,ErrataBatchOutput
from ..services.window_service import list_windows,annotate,list_errata_batches,create_errata
router=APIRouter(tags=['windows'])
@router.get('/studies/{sid}/windows',response_model=list[WindowOutput])
def index(sid:int,db:Session=Depends(get_db),user=Depends(current_user)):return list_windows(db,sid)
@router.get('/studies/{sid}/errata',response_model=list[ErrataBatchOutput])
def errata_index(sid:int,db:Session=Depends(get_db),user=Depends(current_user)):return list_errata_batches(db,sid)
@router.post('/studies/{sid}/errata',response_model=ErrataBatchOutput,status_code=201)
def errata_import(sid:int,data:ErrataImport,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN,Role.ANALYST))):return create_errata(db,sid,data,user)
@router.patch('/windows/{wid}')
def update(wid:int,data:WindowAnnotation,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN,Role.ANALYST))):return annotate(db,wid,data,user)
