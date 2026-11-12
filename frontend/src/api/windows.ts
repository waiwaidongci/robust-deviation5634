import {request} from './client';import {Window,ErrataBatch,ErrataImportInput} from '../types/domain';
export const getWindows=(id:number)=>request<Window[]>(`/studies/${id}/windows`);
export const annotateWindow=(id:number,note:string)=>request<Window>(`/windows/${id}`,{method:'PATCH',body:JSON.stringify({note})});
export const getErrataBatches=(id:number)=>request<ErrataBatch[]>(`/studies/${id}/errata`);
export const importErrata=(id:number,body:ErrataImportInput)=>request<ErrataBatch>(`/studies/${id}/errata`,{method:'POST',body:JSON.stringify(body)});
