import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from .live_window import event_time_status
from .util import save, now

def connect(root):
    root=Path(root); root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'analysis.sqlite',timeout=60)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, live_json TEXT NOT NULL, counts_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS texts(id INTEGER PRIMARY KEY, text TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
        candidate_topic INTEGER, topic INTEGER, method TEXT);
      CREATE TABLE IF NOT EXISTS events(live_id TEXT, source_row INTEGER, ts INTEGER, kind TEXT,
        text_id INTEGER, payload_type TEXT, PRIMARY KEY(live_id,source_row));
      CREATE INDEX IF NOT EXISTS event_text ON events(text_id);
      CREATE INDEX IF NOT EXISTS event_time ON events(live_id,ts);
      CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY, stage TEXT, status TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, error TEXT);
      CREATE TABLE IF NOT EXISTS jobs(stage TEXT,text_id INTEGER,batch_id INTEGER,status TEXT,topic INTEGER,
        PRIMARY KEY(stage,text_id));
      CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,batch_id INTEGER,attempt INTEGER,
        started_at TEXT,seconds REAL,status TEXT,usage_json TEXT,output_path TEXT,error TEXT);
    ''')
    if 'severity_score' not in {row[1] for row in db.execute('PRAGMA table_info(texts)')}:
        db.execute('ALTER TABLE texts ADD COLUMN severity_score INTEGER')
    db.commit();return db

def ingest(root,live,events):
    import json
    counts=Counter()
    with closing(connect(root)) as db,db:
        # Replace this source's event membership, preserving same-text decisions.
        db.execute('DELETE FROM events WHERE live_id=?',(live['liveId'],))
        for row in events:
            counts['source_rows']+=1
            kind=row['event_type']
            if kind not in ('Message','SC'):
                counts['other_events']+=1;continue
            status=event_time_status(live,row['timestamp_ms'])
            if status!='inside':counts[status]+=1;continue
            payload=row['payload'];text=None
            if row['payload_kind']!=2 and isinstance(payload,list) and payload and isinstance(payload[0],str) and payload[0].strip():
                text=payload[0]
            if kind=='SC' and text and text.strip().casefold()=='superchat':text=None
            cid=None
            if text is not None:
                db.execute('INSERT OR IGNORE INTO texts(text,kind) VALUES(?,?)',(text,kind))
                if kind=='SC':db.execute("UPDATE texts SET kind='SC' WHERE text=?",(text,))
                cid=db.execute('SELECT id FROM texts WHERE text=?',(text,)).fetchone()[0]
                # Literal bracket rule is explicit policy, not semantic understanding.
                if '【' in text or '】' in text:
                    db.execute("UPDATE texts SET candidate_topic=0,topic=0,method='literal_bracket_rule' WHERE id=?",(cid,))
                counts['readable_text']+=1
            else:counts['nontext_or_missing_body']+=1
            counts[kind]+=1
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                       (live['liveId'],row['source_row'],row['timestamp_ms'],kind,cid,'text' if text is not None else 'unreadable'))
        db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?)',(live['liveId'],json.dumps(live,ensure_ascii=False),json.dumps(counts)))
    return dict(counts)

def summary(root):
    import json
    with closing(connect(root)) as db:
        events=db.execute('SELECT count(*) FROM events').fetchone()[0]
        counts=dict(db.execute('SELECT coalesce(t.topic,6),count(*) FROM events e LEFT JOIN texts t ON e.text_id=t.id GROUP BY coalesce(t.topic,6)'))
        pending=db.execute('SELECT count(*) FROM texts t WHERE topic IS NULL AND EXISTS(SELECT 1 FROM events e WHERE e.text_id=t.id)').fetchone()[0]
        unique=db.execute('SELECT count(DISTINCT text_id) FROM events').fetchone()[0]
        pending_scores=db.execute('SELECT count(*) FROM texts t WHERE topic=5 AND severity_score IS NULL AND EXISTS(SELECT 1 FROM events e WHERE e.text_id=t.id)').fetchone()[0]
        usage=Counter();seconds=0;attempt_count=0
        for row in db.execute('SELECT seconds,usage_json FROM attempts'):
            seconds+=row[0] or 0;attempt_count+=1
            usage.update({k:v for k,v in json.loads(row[1] or '{}').items() if isinstance(v,(int,float))})
        batches=[dict(r) for r in db.execute('SELECT stage,status,count(*) AS count FROM batches GROUP BY stage,status')]
        return dict(updated_at=now(),events=events,unique_texts=unique,pending_texts=pending,pending_scores=pending_scores,topic_counts=counts,
                    model_attempts=attempt_count,model_worker_seconds=seconds,usage=dict(usage),batches=batches,
                    sources=db.execute('SELECT count(*) FROM sources').fetchone()[0],
                    unreadable_events=db.execute('SELECT count(*) FROM events WHERE text_id IS NULL').fetchone()[0])
