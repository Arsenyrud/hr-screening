"""Сквозная проверка GPU при запущенном приложении."""

import argparse,json,time,httpx
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--pdf',action='store_true')
args=parser.parse_args()
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=20) as c:
    for _ in range(100):
        try:
            if c.get('/health').status_code==200:break
        except httpx.ConnectError:pass
        time.sleep(.1)
    login=c.post('/api/login',json={'username':'recruiter','password':'Recruiter-2026!'});login.raise_for_status()
    c.headers['Authorization']='Bearer '+login.json()['token']
    if args.pdf:
        resumes=c.get('/api/resumes');resumes.raise_for_status();resumes=resumes.json()
        assert resumes and all(x.get('document',{}).get('format')=='pdf' for x in resumes)
    started=time.monotonic();r=c.post('/api/tasks',json={'vacancy_id':'v-python'});r.raise_for_status();task=r.json();states=[]
    while time.monotonic()-started<180:
        r=c.get('/api/tasks/'+task['id']);r.raise_for_status();task=r.json()
        if not states or states[-1]!=task['status']:states.append(task['status'])
        if task['status'] in ['waiting','error']:break
        time.sleep(.2)
    assert task['status']=='waiting',task.get('error')
    result=task['result'];assert result['model']['device']=='cuda';assert result['model_note']['device']=='cuda';assert result['model_note']['status']=='ready'
    record={'status':task['status'],'stage':task['stage'],'elapsed_seconds':time.monotonic()-started,'states':states,'semantic':result['model'],'llm':result['model_note'],'candidate_count':len(result['candidates']),'all_have_questions':all(x['questions'] for x in result['candidates']),'draft_count':sum('llm_draft' in x for x in result['candidates']),'human_approval_required':True,'passed':True}
    if args.pdf:record.update(input_format='pdf',pdf_resume_count=len(resumes))
    target='end_to_end_pdf_gpu.json' if args.pdf else 'end_to_end_gpu.json'
    (ROOT/'evidence'/target).write_text(json.dumps(record,ensure_ascii=False,indent=2));print(json.dumps(record,ensure_ascii=False,indent=2))
