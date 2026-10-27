"""Daily 04:00 Asia/Shanghai, with wake/login catch-up and success-only checkpoint."""
import datetime as dt
import os
import shutil
import sys
import re
from zoneinfo import ZoneInfo
from pathlib import Path
from .util import TZ,now,read,save,process_lock
from .deployment import service_command,launchd_install,systemd_install,windows_install,remove_service

def schedule_options(config=None):
    config=config or {};value=config.get('update_at','04:00')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):
        raise ValueError('Daily update time must be HH:MM (00:00..23:59)')
    hour,minute=map(int,value.split(':'));zone=ZoneInfo(config.get('timezone','Asia/Shanghai'))
    return zone,hour,minute

def due_date(clock=None,config=None):
    zone,hour,minute=schedule_options(config)
    clock=(clock or dt.datetime.now(zone)).astimezone(zone)
    before=(clock.hour,clock.minute)<(hour,minute)
    return (clock.date()-dt.timedelta(days=1 if before else 0)).isoformat()

def install(config_path,print_only=False):
    config_path=Path(config_path).resolve();config=read(config_path);root=config_path.parent
    if config['model']['provider']=='openai':
        raise RuntimeError('For API providers install a scheduler with a secret environment supplied by your host; credentials are never written to a task file. See docs/deployment.md.')
    label=f'org.yourliveeye.{config["channel"]["uid"]}.daily-{config["port"]}'
    args=service_command(config_path,'scheduled',prepare=not print_only)
    zone,hour,minute=schedule_options(config)
    result=dict(enabled=not print_only,timezone=str(zone),hour=hour,minute=minute,poll_seconds=900,
                command=args,installed_at=now(),note='15-minute wake-up; at most one automatic attempt per due date; saved incomplete work is retried on the next due date.')
    if print_only:return result
    if (root/'schedule.json').exists() and read(root/'schedule.json').get('enabled'):
        previous=read(root/'schedule.json')
        previous.update({k:result[k] for k in ('timezone','hour','minute','note')})
        save(root/'schedule.json',previous);return previous
    if (root/'last-run.json').exists() and read(root/'last-run.json').get('status')=='success':
        save(root/'scheduler-state.json',{'last_success_due_date':due_date(config=config),'updated_at':now()})
    if sys.platform=='darwin':service=launchd_install(label,args,root,interval=900)
    elif sys.platform.startswith('linux') and shutil.which('systemctl'):service=systemd_install(label,args,root,timer=True)
    elif os.name=='nt':service=windows_install(label,args,root,timer=True)
    else:raise RuntimeError('No system scheduler found; schedule the printed command with cron at 20:00 UTC')
    result.update(service);save(root/'schedule.json',result);return result

def tick(config_path):
    config_path=Path(config_path).resolve();root=config_path.parent;target=due_date(config=read(config_path))
    state_path=root/'scheduler-state.json'
    with process_lock(root/'scheduler.lock'):
        state=read(state_path) if state_path.exists() else {}
        if state.get('last_success_due_date','')>=target:return {'status':'up_to_date','due_date':target}
        if state.get('last_attempt_due_date','')>=target:
            return {'status':'retry_next_day','due_date':target,'reason':'Automatic attempt failed or was interrupted; use resume for an immediate manual retry'}
        from .pipeline import run
        previous=dict(state)
        state.update(last_attempt_due_date=target,updated_at=now());save(state_path,state)
        try:
            # Failed batches get one additional attempt, retaining their attempt IDs.
            report=run(config_path,retry_failed=True)
            if report['status']!='success':raise RuntimeError('Failed run does not advance schedule checkpoint')
        except BlockingIOError:
            save(state_path,previous)
            return {'status':'busy','due_date':target}
        save(state_path,dict(last_success_due_date=target,updated_at=now()))
        return {'status':'updated','due_date':target}

def uninstall(config_path):
    root=Path(config_path).resolve().parent;path=root/'schedule.json'
    if not path.exists():return {'enabled':False}
    config=read(path)
    if config.get('enabled'):remove_service(config)
    config['enabled']=False;save(path,config);return config
