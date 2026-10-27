"""Incremental, source-bound meme review. No streamer dictionary or private IDs.

The existing pipeline lock serializes writers. Immutable source snapshots and
per-packet receipts allow interruption/resume; only a fully reviewed source
replaces its accepted result. Content equality (not paths or mtimes) drives reuse.
"""
import datetime as dt
import json
import threading
import time
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from . import provider
from .aggregation import day_of
from .store import connect
from .util import TZ,read,save,now,log

VERSION='source-bound-double-review-v1'

def obj(properties):
    return dict(type='object',additionalProperties=False,required=list(properties),properties=properties)

INTEGER={'type':'integer'}
TEXT={'type':'string'}
IDS={'type':'array','items':INTEGER}
EPISODE=obj(dict(key=TEXT,title=TEXT,overview=TEXT,first_row=INTEGER,last_row=INTEGER,
                 reply_groups=IDS,evidence_rows=IDS,sc_row=INTEGER,
                 status={'type':'string','enum':['sc_supported','translation_supported']}))
PRIMARY=obj({'windows':{'type':'array','items':obj(dict(id=INTEGER,
    status={'type':'string','enum':['reviewed','insufficient_context']},reason=TEXT,
    episodes={'type':'array','items':EPISODE}))}})
SECONDARY=obj({'items':{'type':'array','items':obj(dict(id=INTEGER,
    decision={'type':'string','enum':['accept','reject']},reason=TEXT))}})

def translated(row):
    return row['kind']=='Message' and ('【' in row['text'] or '】' in row['text'])

def sources(root):
    with closing(connect(root)) as db:
        for source in db.execute('SELECT id,live_json FROM sources ORDER BY id'):
            live=json.loads(source['live_json'])
            rows=[dict(r) for r in db.execute('''SELECT e.source_row AS id,e.ts,e.kind,t.text
                FROM events e JOIN texts t ON t.id=e.text_id WHERE e.live_id=?
                ORDER BY e.ts,e.source_row''',(source['id'],))]
            yield source['id'],dict(start=live['startDate'],end=live['stopDate'],rows=rows)

def windows(snapshot):
    from .site import intervals
    rows=snapshot['rows'];by_day=defaultdict(list)
    for row in rows:by_day[day_of(row['ts'])].append(row)
    result=[]
    for day,day_rows in sorted(by_day.items()):
        midnight=int(dt.datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()*1000)
        ranges=[dict(start=max(snapshot['start'],midnight),end=min(snapshot['end'],midnight+86400000-1))]
        for start,end in intervals(ranges):
            core=[r for r in day_rows if start<=r['ts']<end]
            audience=defaultdict(list)
            for r in core:
                if r['kind']=='Message' and not translated(r):audience[r['text']].append(r)
            groups=[dict(g=rs[0]['id'],text=text,occ=[[r['id'],r['ts']] for r in rs]) for text,rs in audience.items()]
            sc=[r for r in rows if r['kind']=='SC' and r['ts']<end]
            tr=[r for r in rows if translated(r) and start-300000<=r['ts']<end+300000]
            if not tr:
                all_tr=[r for r in rows if translated(r)]
                tr=[r for r in all_tr if r['ts']<start][-10:]+[r for r in all_tr if r['ts']>=end][:10]
            if not groups:continue
            result.append(dict(id=len(result)+1,day=day,start=start,end=end,audience=groups,sc=sc,translations=tr))
    return result

def packets(snapshot,budget):
    result=[];current=[];size=0
    for window in windows(snapshot):
        # Split busy windows without dropping audience groups. Context remains
        # complete; each shard can only quote its own audience groups.
        groups=window['audience'];parts=[];part=[]
        for group in groups:
            candidate=dict(window,audience=part+[group])
            if part and len(json.dumps(candidate,ensure_ascii=False).encode('utf-8'))>budget:
                parts.append(dict(window,audience=part));part=[]
            part.append(group)
        if part:parts.append(dict(window,audience=part))
        for item in parts:
            item=dict(item,id=sum(len(p['windows']) for p in result)+len(current)+1)
            n=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
            if n>budget:raise ValueError('Meme context exceeds batch byte budget; raise --batch-bytes; input was not truncated')
            if current and (size+n>budget or len(current)>=5):
                result.append({'windows':current});current=[];size=0
            current.append(item);size+=n
    if current:result.append({'windows':current})
    return result

def public(row,sid):
    return dict(id=f'{sid}:{row["id"]}',ts=row['ts'],text=row['text'],
                source_url=f'https://danmakus.com/live/{sid}')

def materialize(window,episode,sid):
    groups={g['g']:g for g in window['audience']}
    if not episode['reply_groups'] or len(set(episode['reply_groups']))!=len(episode['reply_groups']):raise ValueError('Invalid audience groups')
    # The source explicitly maps every occurrence to its identical-text group.
    # Accept an occurrence alias only through that exact map; never guess an ID.
    aliases={rid:g['g'] for g in window['audience'] for rid,_ in g['occ']}
    selected=[groups[g] for g in dict.fromkeys(aliases.get(g,g) for g in episode['reply_groups'])]
    audience={rid:dict(id=rid,ts=ts,text=g['text'],kind='Message') for g in selected for rid,ts in g['occ']}
    all_audience={rid:dict(id=rid,ts=ts,text=g['text'],kind='Message') for g in groups.values() for rid,ts in g['occ']}
    first,last=audience[episode['first_row']],audience[episode['last_row']]
    lower,upper=(first['ts'],first['id']),(last['ts'],last['id'])
    if lower>upper:raise ValueError('Reversed reaction bounds')
    reactions=sorted((r for r in audience.values() if lower<=(r['ts'],r['id'])<=upper),key=lambda r:(r['ts'],r['id']))
    contexts={r['id']:r for r in window['sc']+window['translations']}
    evidence=[(all_audience|contexts)[rid] for rid in episode['evidence_rows']]
    if first['id'] not in episode['evidence_rows']:raise ValueError('Missing first reaction evidence')
    sc=None
    if episode['status']=='sc_supported':
        sc=contexts[episode['sc_row']]
        if sc['kind']!='SC' or (sc['ts'],sc['id'])>=lower:raise ValueError('Future or wrong-kind SC')
        if sc['id'] not in episode['evidence_rows'] or not any(r['id'] not in (sc['id'],first['id']) for r in evidence):raise ValueError('SC lacks connecting evidence')
    elif episode['status']=='translation_supported':
        if episode['sc_row']!=0 or not any(translated(r) for r in evidence):raise ValueError('Missing translation evidence')
    else:raise ValueError('Unsupported episode')
    if not all(isinstance(episode[k],str) and episode[k].strip() for k in ('key','title','overview')):raise ValueError('Missing explanation')
    return dict(day=window['day'],meme_key=episode['key'],title=episode['title'],overview=episode['overview'],
        first_reaction=public(first,sid),reaction_rows=[public(r,sid) for r in reactions],
        context_evidence=[public(r,sid)|{'kind':r['kind']} for r in evidence if r['id']!=first['id']],
        related_sc=public(sc,sid) if sc else None,evidence_kind=episode['status'],
        review_source='模型全窗口初审与独立二审；原文引用核对；非人工金标或音视频核验')

def validate_primary(payload,packet,sid):
    expected={w['id']:w for w in packet['windows']};answers=payload['windows']
    ids=[a['id'] for a in answers]
    if len(ids)!=len(expected) or set(ids)!=set(expected):raise ValueError('Meme window IDs differ')
    candidates=[]
    for answer in answers:
        if answer['status'] not in ('reviewed','insufficient_context'):raise ValueError('Invalid window status')
        if answer['status']=='insufficient_context' and answer['episodes']:raise ValueError('Unsupported episode in insufficient context')
        for episode in answer['episodes']:
            candidates.append(materialize(expected[answer['id']],episode,sid))
    return candidates

def validate_secondary(payload,candidates):
    answers=payload['items'];ids=[r['id'] for r in answers]
    if len(ids)!=len(candidates) or set(ids)!=set(range(len(candidates))):raise ValueError('Secondary IDs differ')
    if any(r['decision'] not in ('accept','reject') for r in answers):raise ValueError('Invalid secondary decision')
    return [candidates[r['id']] for r in answers if r['decision']=='accept']

def phase(folder,name,packet,prompt,settings,schema,validator,caller,retry_failed):
    path=folder/(name+'.json');state=read(path) if path.exists() else {'attempts':0,'status':'pending'}
    if state['status']=='complete':return state['result']
    # Recover a previously received valid response after interruption or a
    # source-ID parser fix, without another inference or modifying raw receipts.
    for attempt in range(state['attempts'],0,-1):
        raw=folder/'attempts'/f'{name}-{attempt}.json'
        metrics=folder/'attempts'/f'{name}-{attempt}.metrics.json'
        if not raw.exists() or not metrics.exists() or read(metrics).get('error'):continue
        try:result=validator(read(raw))
        except (ValueError,KeyError,TypeError):continue
        state.update(status='complete',result=result,finished_at=now(),recovered_attempt=attempt);save(path,state)
        return result
    if state['status']=='failed' and not retry_failed:raise RuntimeError('Meme batch failed; inspect receipts, then --retry-failed')
    # Explicit retry grants one new bounded budget; attempts and receipts are retained.
    ceiling=state['attempts']+settings['max_attempts'] if retry_failed else settings['max_attempts']
    while state['attempts']<ceiling:
        if (folder.parents[4]/'stop-claim').exists():raise RuntimeError('Meme review interrupted by stop-claim')
        state['attempts']+=1;state['status']='running';save(path,state)
        payload,metrics=caller(packet,prompt,settings,folder/'attempts'/f'{name}-{state["attempts"]}',schema)
        try:
            if metrics['error']:raise RuntimeError(metrics['error'])
            result=validator(payload)
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:
            state.update(status='failed',error=type(exc).__name__)
            save(path,state)
            if state['attempts']>=ceiling:raise RuntimeError('Meme review failed; previous published topics retained') from exc
        else:
            state.update(status='complete',result=result,finished_at=now());save(path,state)
            return result
    raise RuntimeError('Meme retry limit reached')

def update(root,config,caller=provider.request,retry_failed=False):
    root=Path(root);base=root/'memes';index_path=base/'index.json'
    index=read(index_path) if index_path.exists() else {};started=time.monotonic();changed=[];reused=[]
    settings=dict(config['model'],**config.get('meme_model',{}))
    prompt_dir=Path(__file__).parent/'prompts'
    prompts={name:(prompt_dir/f'meme_{name}.txt').read_text(encoding='utf-8') for name in ('primary','secondary')}
    prompts={name:text.replace('{{CHANNEL}}',json.dumps(config['channel'],ensure_ascii=False)) for name,text in prompts.items()}
    for sid,snapshot in sources(root):
        prior=index.get(sid);folder=base/'runs'/str(prior['run']) if prior else None
        if not folder or read(folder/'source.json')!=snapshot:
            runs=base/'runs';runs.mkdir(parents=True,exist_ok=True)
            number=max((int(p.name) for p in runs.iterdir() if p.name.isdigit()),default=0)+1
            folder=runs/str(number);save(folder/'source.json',snapshot)
            chunks=packets(snapshot,settings['batch_bytes'])
            save(folder/'packets.json',chunks);save(folder/'prompts.json',prompts)
            save(folder/'settings.json',settings)
            # Reuse whole packets whose actual input is unchanged after a correction.
            if prior:
                old=base/'runs'/str(prior['run']);old_packets=read(old/'packets.json')
                for i,packet in enumerate(chunks):
                    if i<len(old_packets) and packet==old_packets[i]:
                        for name in ('primary','secondary'):
                            path=old/'chunks'/str(i)/(name+'.json')
                            if path.exists() and read(path)['status']=='complete':save(folder/'chunks'/str(i)/(name+'.json'),read(path))
            index[sid]=dict(run=number,published=prior.get('published') if prior else None,status='pending',version=VERSION)
            save(index_path,index)
        if index[sid]['status']=='complete':reused.append(sid);continue
        prompts_frozen=read(folder/'prompts.json');settings_frozen=read(folder/'settings.json');chunks=read(folder/'packets.json')
        mutex=threading.Lock();done=0
        def process(i):
            nonlocal done
            from .checkpoint import boundary
            packet=chunks[i];work=folder/'chunks'/str(i)
            candidates=phase(work,'primary',packet,prompts_frozen['primary'],settings_frozen,PRIMARY,
                lambda payload:validate_primary(payload,packet,sid),caller,retry_failed)
            if candidates:
                second={'items':[dict(id=n,candidate=c) for n,c in enumerate(candidates)]}
                accepted=phase(work,'secondary',second,prompts_frozen['secondary'],settings_frozen,SECONDARY,
                    lambda payload:validate_secondary(payload,candidates),caller,retry_failed)
            else:accepted=[]
            with mutex:
                done+=1
                save(base/'progress.json',dict(status='running',source=sid,packets_complete=done,packets_total=len(chunks),updated_at=now()))
            log('meme_packet',source=sid,packet=i,accepted=len(accepted),complete=done,total=len(chunks))
            boundary(root)
            return accepted
        try:
            with ThreadPoolExecutor(max_workers=settings_frozen['concurrency']) as pool:
                accepted=[c for result in pool.map(process,range(len(chunks))) for c in result]
            save(folder/'accepted.json',accepted)
            index[sid].update(status='complete',published=index[sid]['run'],updated_at=now(),episodes=len(accepted));save(index_path,index)
        except BaseException:
            save(base/'progress.json',dict(status='failed',source=sid,updated_at=now()));raise
        changed.append(sid)
    result=dict(status='complete' if changed else 'reused',changed_sources=len(changed),reused_sources=len(reused),seconds=round(time.monotonic()-started,2),updated_at=now())
    save(base/'progress.json',result);return result

def load(root):
    base=Path(root)/'memes';index=read(base/'index.json') if (base/'index.json').exists() else {}
    accepted=[];states={}
    for sid,snapshot in sources(root):
        entry=index.get(sid)
        current=entry and entry['status']=='complete' and read(base/'runs'/str(entry['run'])/'source.json')==snapshot
        days={day_of(r['ts']) for r in snapshot['rows']}
        for day in days:states.setdefault(day,[]).append('reviewed' if current else 'not_reviewed')
        if current:accepted.extend(read(base/'runs'/str(entry['published'])/'accepted.json'))
    return accepted,{day:'reviewed' if all(s=='reviewed' for s in values) else 'not_reviewed' for day,values in states.items()}

def rank(accepted,day,limit,period=None):
    groups=defaultdict(lambda:dict(rows={},episodes=[]))
    for item in accepted:
        if item['day']!=day:continue
        rows=[r for r in item['reaction_rows'] if period is None or period[0]<=r['ts']<period[1]]
        if not rows:continue
        group=groups[item['meme_key']];group['rows'].update({r['id']:r for r in rows});group['episodes'].append((item,rows))
    result=[]
    for key,group in groups.items():
        item,rows=min(group['episodes'],key=lambda pair:(-len(pair[1]),pair[1][0]['ts']))
        public_item={k:v for k,v in item.items() if k not in ('reaction_rows','day')}
        counts=Counter(r['text'] for r in rows)
        public_item.update(reaction_count=len(group['rows']),audience_replies=[{'text':text} for text,_ in counts.most_common(5)],period_reaction=rows[0])
        result.append(public_item)
    return sorted(result,key=lambda r:(-r['reaction_count'],r['first_reaction']['ts'],r['meme_key']))[:limit]
