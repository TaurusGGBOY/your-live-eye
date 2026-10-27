"""Resumable classification and category-preserving expression intensity."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from . import provider
from .store import connect,summary
from .util import log,now,read,save

def prompt_for(stage,channel):
    template=(Path(__file__).parent/'prompts'/f'{stage}.txt').read_text(encoding='utf-8')
    return template.replace('{{CHANNEL}}',json.dumps(channel,ensure_ascii=False))

def queue(root,stage,settings):
    with closing(connect(root)) as db,db:
        condition={'primary':'t.candidate_topic IS NULL','primary_quarrel':'t.candidate_topic IS NULL','review':'t.candidate_topic=5 AND t.topic IS NULL',
                   'review_scored':'t.candidate_topic=5 AND t.topic IS NULL',
                   'severity':'t.topic=5 AND t.severity_score IS NULL',
                   'intensity':'t.topic=5 AND t.severity_score IS NULL'}[stage]
        rows=db.execute(f'''SELECT t.id,t.text FROM texts t WHERE {condition}
            AND EXISTS(SELECT 1 FROM events e WHERE e.text_id=t.id)
            AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.stage=? AND j.text_id=t.id) ORDER BY t.id''',(stage,)).fetchall()
        limit=settings['batch_size'] if stage in ('primary','primary_quarrel') else settings.get('score_batch_size',2048) if stage=='intensity' else settings['review_batch_size']
        batch=[];size=0
        def flush():
            nonlocal batch,size
            if not batch:return
            bid=db.execute("INSERT INTO batches(stage,status) VALUES(?,'pending')",(stage,)).lastrowid
            db.executemany("INSERT INTO jobs VALUES(?,?,?,'pending',NULL)",[(stage,r['id'],bid) for r in batch])
            batch=[];size=0
        for row in rows:
            n=len(row['text'].encode('utf-8'))
            if n>settings['batch_bytes']:raise ValueError('One message exceeds configured batch byte budget; raise --batch-bytes or choose a larger-context model; no truncation.')
            if batch and (len(batch)>=limit or size+n>settings['batch_bytes']):flush()
            batch.append(row);size+=n
        flush()

def model_rows(db,stage,ids):
    result=[]
    for cid in ids:
        row=dict(db.execute('SELECT id,text,kind FROM texts WHERE id=?',(cid,)).fetchone())
        if stage in ('review','review_scored','severity'):
            contexts=[]
            for event in db.execute('SELECT live_id,source_row,ts FROM events WHERE text_id=? ORDER BY ts LIMIT 3',(cid,)):
                neighbors=[dict(r) for r in db.execute('''SELECT e.ts,e.kind,t.text FROM events e JOIN texts t ON e.text_id=t.id
                    WHERE e.live_id=? AND e.ts BETWEEN ? AND ? AND e.source_row<>?
                    ORDER BY abs(e.ts-?) LIMIT 8''',(event['live_id'],event['ts']-60000,event['ts']+60000,event['source_row'],event['ts']))]
                contexts.append({'live_id':event['live_id'],'ts':event['ts'],'neighbors':sorted(neighbors,key=lambda x:x['ts'])})
            row['contexts']=contexts
        result.append(row)
    return result

def execute(root,stage,settings,channel,caller=provider.call,enqueue=True):
    root=Path(root)
    if enqueue:queue(root,stage,settings)
    prompt=prompt_for(stage,channel)
    frozen=root/'prompts'/f'{stage}.txt'
    if frozen.exists() and frozen.read_text(encoding='utf-8')!=prompt:
        raise RuntimeError('Prompt changed for this dataset. Use a new --state directory to preserve old decisions.')
    frozen.parent.mkdir(exist_ok=True);frozen.write_text(prompt,encoding='utf-8')
    with closing(connect(root)) as db,db:
        # The caller holds the whole-pipeline OS lock. Running rows are from a crashed process.
        db.execute("UPDATE batches SET status='pending',error='interrupted' WHERE stage=? AND status='running'",(stage,))
    mutex=threading.Lock()
    def worker():
        with closing(connect(root)) as db:
            while not (root/'stop-claim').exists():
                with mutex,db:
                    job=db.execute("SELECT id,attempts FROM batches WHERE stage=? AND status IN ('pending','retry') ORDER BY id LIMIT 1",(stage,)).fetchone()
                    if not job:return
                    bid,attempt=job['id'],job['attempts']+1
                    if attempt>settings['max_attempts'] and db.execute('SELECT error FROM batches WHERE id=?',(bid,)).fetchone()[0]!='explicit_retry':
                        db.execute("UPDATE batches SET status='failed',error='retry_limit' WHERE id=?",(bid,));continue
                    db.execute("UPDATE batches SET status='running',attempts=? WHERE id=?",(attempt,bid))
                ids=[r[0] for r in db.execute("SELECT text_id FROM jobs WHERE batch_id=? AND status!='complete' ORDER BY text_id",(bid,))]
                rows=model_rows(db,stage,ids)
                started=now()
                call_settings=dict(settings,max_output_value=100) if stage=='severity' else settings
                if stage=='intensity':call_settings=dict(settings,max_output_value=100,min_output_value=1)
                if stage=='review_scored':call_settings=dict(settings,response_kind='scored_review')
                labels,metrics=caller(rows,prompt,call_settings,root/'attempts'/f'{stage}-{bid:06d}-{attempt}')
                with db:
                    if not metrics['error']:
                        for cid,value in labels.items():
                            topic=value['topic'] if stage=='review_scored' else value
                            db.execute("UPDATE jobs SET status='complete',topic=? WHERE stage=? AND text_id=?",(topic,stage,cid))
                            if stage in ('primary','primary_quarrel'):
                                db.execute('UPDATE texts SET candidate_topic=?,topic=?,method=? WHERE id=?',
                                           (topic,topic,'primary_model' if stage=='primary' else 'primary_quarrel_v1',cid))
                            elif stage=='review':
                                db.execute("UPDATE texts SET topic=?,method='scoped_context_review' WHERE id=?",(topic,cid))
                            elif stage=='review_scored':
                                db.execute("UPDATE texts SET topic=?,severity_score=?,method='scoped_review_with_strength' WHERE id=?",
                                           (topic,value['severity_score'],cid))
                            else:
                                db.execute('UPDATE texts SET severity_score=? WHERE id=?',(topic,cid))
                    remaining=db.execute("SELECT count(*) FROM jobs WHERE batch_id=? AND status!='complete'",(bid,)).fetchone()[0]
                    error=metrics['error'] or ('missing_output_ids' if remaining else None)
                    status='complete' if not error else 'failed' if attempt>=settings['max_attempts'] else 'retry'
                    db.execute('UPDATE batches SET status=?,error=? WHERE id=?',(status,error,bid))
                    db.execute('INSERT INTO attempts(batch_id,attempt,started_at,seconds,status,usage_json,output_path,error) VALUES(?,?,?,?,?,?,?,?)',
                               (bid,attempt,started,metrics['seconds'],status,json.dumps(metrics['usage']),metrics['output_path'],error))
                log('model_batch',stage=stage,batch=bid,attempt=attempt,status=status,items=len(rows),valid=len(labels),seconds=round(metrics['seconds'],2),error=error)
                with mutex:save(root/'progress.json',summary(root))
                from .checkpoint import boundary
                boundary(root)
                if error and status=='retry':time.sleep(min(20,2**attempt))
    with ThreadPoolExecutor(max_workers=settings['concurrency']) as pool:
        for future in [pool.submit(worker) for _ in range(settings['concurrency'])]:future.result()
    with closing(connect(root)) as db:
        incomplete=db.execute("SELECT count(*) FROM batches WHERE stage=? AND status!='complete'",(stage,)).fetchone()[0]
    if incomplete:raise RuntimeError(f'{stage}: {incomplete} incomplete/failed batches. Inspect status; resume pending work or explicitly retry failures.')

def classify(root,settings,channel,caller=provider.call):
    with closing(connect(root)) as db,db:
        legacy=db.execute("SELECT count(*) FROM batches WHERE stage='primary' AND status!='complete'").fetchone()[0]
        # Retain completed decisions and receipts. An unfinished old second
        # classifier must not silently remove category 5 after this upgrade.
        db.execute("UPDATE batches SET status='superseded' WHERE stage IN ('review','review_scored','severity') AND status!='complete'")
        db.execute("UPDATE jobs SET status='superseded' WHERE stage IN ('review','review_scored','severity') AND status!='complete'")
        db.execute("UPDATE texts SET topic=5,method='primary_preserved_on_upgrade' WHERE candidate_topic=5 AND topic IS NULL")
    if legacy:execute(root,'primary',settings,channel,caller,enqueue=False)
    execute(root,'primary_quarrel',settings,channel,caller)
    execute(root,'intensity',settings,channel,caller)
    result=summary(root);save(Path(root)/'progress.json',result)
    if result['pending_texts']:raise RuntimeError('Unprocessed readable text remains')
    return result
