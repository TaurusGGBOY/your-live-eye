import datetime as dt
import json
import time
from contextlib import closing
from pathlib import Path
from .source import Source,select_sessions
from .store import connect,ingest,summary
from .classifier import classify
from .util import TZ,log,now,read,save,process_lock

def run(config_path,initial=False,retry_failed=False):
    config_path=Path(config_path).resolve(); config=read(config_path)
    root=config_path.parent; source=Source(config['source_base']); began=time.monotonic()
    with process_lock(root/'pipeline.lock'):
        report={'started_at':now(),'status':'running','channel':config['channel']}
        save(root/'last-run.json',report)
        try:
            if (root/'stop-claim').exists():raise RuntimeError('Remove stop-claim to resume model work')
            catalogue=source.catalogue(config['channel']['uid'])
            save(root/'catalogue.json',dict(fetched_at=now(),data=catalogue))
            scope=config.get('date','all')
            lives,selection=select_sessions(catalogue,scope,config.get('fallback_latest',False))
            # Catch up every finished session since the original successful run.
            checkpoint=root/'checkpoint.json'
            if checkpoint.exists() and not initial and scope!='all':
                baseline=read(checkpoint)['earliest_start']
                cutoff=dt.datetime.now(TZ).timestamp()*1000
                lives=[x for x in catalogue['lives'] if x.get('isFinish') and x.get('stopDate')
                       and x['startDate']>=baseline and x['stopDate']<=cutoff]
                if not lives:raise RuntimeError('Current catalogue no longer covers the saved start; checkpoint unchanged')
                if min(x['startDate'] for x in catalogue['lives'])>baseline:
                    raise RuntimeError('Catalogue coverage gap since checkpoint; import missing sessions before advancing')
                selection={'selection':'incremental_catch_up','earliest_start':baseline}
            with closing(connect(root)) as db:
                known={r['id']:json.loads(r['live_json']) for r in db.execute('SELECT id,live_json FROM sources')}
            threshold=(dt.datetime.now(TZ)-dt.timedelta(days=3)).timestamp()*1000
            selected_ids={x['liveId'] for x in lives}
            coverage=dict(scope=scope,selected=len(lives),selected_ids=[x['liveId'] for x in lives],
                          deferred_ids=[x['liveId'] for x in catalogue['lives'] if x['liveId'] not in selected_ids],
                          imported=0,errors=[],updated_at=now())
            save(root/'coverage.json',coverage)
            for live in sorted(lives,key=lambda x:x['startDate']):
                previous=known.get(live['liveId'])
                # Re-fetch a three-day overlap for archive corrections and delayed uploads.
                refresh=bool(previous and (live['stopDate']>=threshold or previous.get('danmakusCount')!=live.get('danmakusCount')))
                if not previous or refresh:
                    try:
                        events=source.acquire(live,config['channel'],root,refresh)
                        counts=ingest(root,live,events)
                        log('source_imported',live_id=live['liveId'],counts=counts)
                    except Exception as error:
                        coverage['errors'].append({'live_id':live['liveId'],'error':str(error)})
                        log('source_failed',live_id=live['liveId'],error=str(error))
                        save(root/'coverage.json',coverage)
                        from .checkpoint import boundary
                        boundary(root)
                        continue
                coverage['imported']+=1
                coverage['updated_at']=now();save(root/'coverage.json',coverage)
                from .checkpoint import boundary
                boundary(root)
            if retry_failed:
                with closing(connect(root)) as db,db:
                    # Preserve monotonically increasing attempt IDs and old receipts.
                    db.execute("UPDATE batches SET status='pending',error='explicit_retry' WHERE status='failed'")
            save(root/'selection.json',selection)
            log('classification_started',**summary(root))
            classify(root,config['model'],config['channel'])
            if coverage['errors']:
                raise RuntimeError(f"{len(coverage['errors'])} source downloads incomplete; successful sources and model decisions are saved; previous site retained")
            from .site import build
            site=build(root,config)
            if config.get('deploy'):
                from .deployment import deploy,verify
                access=deploy(root,config)
                verify(root,config,access)
            result=summary(root)
            report.update(status='success',finished_at=now(),wall_seconds=time.monotonic()-began,
                          selection=selection,result=result,site=str(site))
            if config.get('deploy'):report['access']=read(root/'access.json')
            save(root/'last-run.json',report)
            earliest=min(x['startDate'] for x in lives)
            save(checkpoint,dict(last_success_at=now(),earliest_start=min(earliest,read(checkpoint)['earliest_start']) if checkpoint.exists() else earliest,
                                 last_finished_stop=max(x['stopDate'] for x in lives)))
            log('complete',**report)
            return report
        except BaseException as error:
            report.update(status='failed',finished_at=now(),wall_seconds=time.monotonic()-began,error=str(error),error_type=type(error).__name__)
            save(root/'last-run.json',report);raise
