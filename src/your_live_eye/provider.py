"""Model transports. Credentials stay with Codex or in environment variables."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
import requests
from .util import save
from .validation import salvage_pairs,salvage_scored

def codex_executable():
    binary=shutil.which('codex')
    if binary:return binary
    candidate=Path.home()/'.local/bin/codex'
    if candidate.is_file():return str(candidate)
    raise RuntimeError('Install Codex CLI and complete `codex login`, or choose --provider openai and configure its environment variables.')

def call(rows,prompt,settings,stem):
    width=3 if settings.get('response_kind')=='scored_review' else 2
    schema={'type':'object','additionalProperties':False,'required':['items'],
            'properties':{'items':{'type':'array','minItems':len(rows),'maxItems':len(rows),
                         'items':{'type':'array','items':{'type':'integer'},'minItems':width,'maxItems':width}}}}
    payload,metrics=request(rows,prompt,settings,stem,schema)
    labels={}
    if not metrics['error']:
        try:
            expected=[{'content_id':r['id']} for r in rows]
            labels,metrics['audit']=salvage_scored(payload,expected) if width==3 else salvage_pairs(payload,expected,settings.get('max_output_value',7),settings.get('min_output_value',0))
        except (KeyError,ValueError,TypeError):metrics['error']='invalid_model_output'
    save(Path(stem).with_suffix('.metrics.json'),metrics)
    return labels,metrics

def request(rows,prompt,settings,stem,schema):
    """Shared transport for classification and source-bound semantic review."""
    stem=Path(stem);stem.parent.mkdir(parents=True,exist_ok=True)
    output=stem.with_suffix('.json')
    save(stem.with_suffix('.schema.json'),schema)
    save(stem.with_suffix('.request.json'),dict(settings=settings,items=rows))
    content=prompt+'\n'+json.dumps(rows,ensure_ascii=False,separators=(',',':'))
    started=time.monotonic();usage={};error=None;payload=None;audit={}
    try:
        if settings['provider']=='codex':
            runtime=Path(os.environ.get('YOUR_LIVE_EYE_TMP','/tmp/codextmp/your_live_eye-model'))
            runtime.mkdir(parents=True,exist_ok=True)
            cmd=[codex_executable(),'exec','--ignore-user-config','--ephemeral','--strict-config',
                 '--skip-git-repo-check','-C',str(runtime),'-s','read-only','-m',settings['model'],
                 '-c','model_reasoning_effort='+json.dumps(settings['reasoning']),
                 '-c','service_tier='+json.dumps(settings['tier']),'-c','approval_policy="never"',
                 '-c','features.shell_tool=false','-c','features.apps=false',
                 '--output-schema',str(stem.with_suffix('.schema.json')),'--json','-o',str(output),'-']
            save(stem.with_suffix('.command.json'),cmd)
            events=stem.with_suffix('.events.jsonl')
            with events.open('w',encoding='utf-8') as out,stem.with_suffix('.stderr.log').open('w',encoding='utf-8') as err:
                result=subprocess.run(cmd,input=content,text=True,encoding='utf-8',stdout=out,stderr=err,timeout=settings['timeout'])
            for line in events.read_text(encoding='utf-8').splitlines():
                try:event=json.loads(line)
                except ValueError:continue
                if event.get('type')=='turn.completed':usage=event.get('usage',{})
                if event.get('type','').startswith('item.') and event.get('item',{}).get('type') not in (None,'reasoning','agent_message'):
                    error='unexpected_tool_use'
            if result.returncode:error=f'codex_exit_{result.returncode}'
            if error:raise RuntimeError(error)
            payload=json.loads(output.read_text(encoding='utf-8'))
        else:
            key=os.environ.get('YOUR_LIVE_EYE_API_KEY') or os.environ.get('OPENAI_API_KEY')
            if not key:raise RuntimeError('Missing YOUR_LIVE_EYE_API_KEY / OPENAI_API_KEY')
            base=(os.environ.get('YOUR_LIVE_EYE_API_BASE') or 'https://api.openai.com/v1').rstrip('/')
            response=requests.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key},
                  json={'model':settings['model'],'messages':[{'role':'user','content':content}],
                        'reasoning_effort':settings['reasoning'],
                        'response_format':{'type':'json_schema','json_schema':{'name':'classification','strict':True,'schema':schema}}},
                  timeout=settings['timeout'])
            if response.status_code!=200:raise RuntimeError('provider_http_'+str(response.status_code))
            result=response.json();raw_usage=result.get('usage',{})
            usage={'input_tokens':raw_usage.get('prompt_tokens',0),'output_tokens':raw_usage.get('completion_tokens',0),
                   'cached_input_tokens':raw_usage.get('prompt_tokens_details',{}).get('cached_tokens',0)}
            payload=json.loads(result['choices'][0]['message']['content']);save(output,payload)
    except subprocess.TimeoutExpired:error='model_timeout'
    except Exception as exc:
        # Never include headers, credentials or provider response bodies in errors.
        if error is None:error=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
    metrics=dict(seconds=time.monotonic()-started,usage=usage,error=error,audit=audit,output_path=str(output))
    save(stem.with_suffix('.metrics.json'),metrics)
    return payload,metrics
