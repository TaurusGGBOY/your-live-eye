"""Static snapshots: Hinome calendar/UI with channel-specific identity and isolated data."""
import datetime as dt
import gzip
import html
import json
import shutil
from collections import Counter,defaultdict
from contextlib import closing
from pathlib import Path
from .aggregation import TOPICS,SENTIMENTS,N_TOPICS,N_VECTOR,zeros,totals,empty_day,calendar_index,day_of
from .store import connect,summary
from .first_screen import embed
from .util import TZ,save,read,now

def intervals(ranges):
    merged=[]
    for r in sorted(ranges,key=lambda x:x['start']):
        if merged and r['start']//60000<=merged[-1]['end']//60000:merged[-1]['end']=max(merged[-1]['end'],r['end'])
        else:merged.append(dict(start=r['start'],end=r['end']))
    result=[]
    for r in merged:
        for start in range(r['start']//60000*60000,r['end']+1,300000):
            result.append((max(start,r['start']),min(start+300000,r['end']+1)))
    return result

def highlights(events,channel,limit):
    # Exact-text frequencies are observable facts, not invented meme explanations.
    texts=defaultdict(list)
    for event in events:
        if event['topic']==3 and event['text'] and len(event['text'].strip())>=2:
            texts[event['text']].append(event)
    ranked=sorted(texts.items(),key=lambda pair:(-len(pair[1]),pair[1][0]['ts']))[:limit]
    return [{'title':f'「{text[:36]}」 · {len(rows)} 次',
             'audience_replies':[{'text':text}], 'first_reaction':{'ts':rows[0]['ts']},
             'period_reaction':{'ts':rows[0]['ts']},'evidence_kind':'exact_text_frequency'} for text,rows in ranked]

def build(root,config):
    root=Path(root);info=summary(root)
    if info['pending_texts']:raise RuntimeError('Cannot publish while readable text remains unprocessed')
    if info['pending_scores']:raise RuntimeError('Attack strength scoring is incomplete; resume classification before publishing')
    channel=config['channel'];days=defaultdict(empty_day);quotes=defaultdict(list)
    from .memes import load,rank
    meme_episodes,meme_states=load(root)
    with closing(connect(root)) as db:
        lives={r['id']:json.loads(r['live_json']) for r in db.execute('SELECT id,live_json FROM sources')}
        exclusions=Counter()
        for row in db.execute('SELECT counts_json FROM sources'):exclusions.update(json.loads(row[0]))
        for row in db.execute('''SELECT e.*,t.text,t.topic,t.method,t.severity_score FROM events e LEFT JOIN texts t ON e.text_id=t.id ORDER BY e.ts,e.live_id,e.source_row'''):
            day=day_of(row['ts']);data=days[day];topic=row['topic'] if row['topic'] is not None else 6
            ti=topic+(8 if row['kind']=='SC' else 0);tone=1 if topic!=6 else 3;si=16+tone+(4 if row['kind']=='SC' else 0)
            bucket=data['minutes'].setdefault(row['ts']//60000*60000,zeros()+[0])
            for vector in (bucket,data['vector']):vector[ti]+=1;vector[si]+=1
            data['images']+=row['text_id'] is None;data['sessions'].add(row['live_id'])
            live=lives[row['live_id']];midnight=int(dt.datetime.fromisoformat(day).replace(tzinfo=TZ).timestamp()*1000)
            data['live_ranges'][row['live_id']]={'session':row['live_id'],'start':max(live['startDate'],midnight),
                'end':min(live['stopDate'],midnight+86400000-1),'source_start':live['startDate'],'source_end':live['stopDate']}
            data['first_ts']=row['ts'] if data['first_ts'] is None else min(data['first_ts'],row['ts'])
            data['last_ts']=row['ts'] if data['last_ts'] is None else max(data['last_ts'],row['ts'])
            quotes[day].append(dict(ts=row['ts'],text=row['text'],topic=topic,severity_score=row['severity_score'] or None,
                                    source_url=f"https://danmakus.com/live/{row['live_id']}"))
    observed=sorted(days)
    if not observed:raise RuntimeError('No messages within verified live intervals; nothing to publish')
    site=root/'site-next'
    if site.exists():shutil.rmtree(site)
    (site/'days').mkdir(parents=True);(site/'insights').mkdir()
    template=Path(__file__).parent/'web'
    for name in ('app.js','style.css','favicon.svg'):shutil.copyfile(template/name,site/name)
    source=(template/'index.html').read_text(encoding='utf-8')
    for key,value in {'CHANNEL_NAME':channel['name'],'LIVE_URL':channel['live_url'],'SOURCE_URL':channel['source_url']}.items():
        source=source.replace('{{'+key+'}}',html.escape(str(value),quote=True))
    (site/'index.html').write_text(source,encoding='utf-8')
    generated=now();total=zeros()
    for day,data in days.items():
        ranges=sorted(data['live_ranges'].values(),key=lambda x:x['start'])
        save(site/'days'/f'{day}.json',dict(day=day,series=totals(data['vector']),
             minutes=[[ts]+v for ts,v in sorted(data['minutes'].items())],sessions=sorted(data['sessions']),
             images=data['images'],interrupts=0,live_ranges=ranges,first_ts=data['first_ts'],last_ts=data['last_ts']))
        periods=[]
        for start,end in intervals(ranges):
            rows=[r for r in quotes[day] if start<=r['ts']<end]
            attacks=sorted((r for r in rows if r['topic']==5),key=lambda r:(-(r['severity_score'] or 0),r['ts']))
            periods.append(dict(start=start,end=end,critical_quotes=attacks[:10],critical_total_count=len(attacks),
                reaction_topics=rank(meme_episodes,day,1,(start,end)) if meme_states.get(day)=='reviewed' else highlights(rows,channel,1)))
        save(site/'insights'/f'{day}.json',dict(day=day,live_only=True,period_insights=periods,
             critical_total_count=sum(r['topic']==5 for r in quotes[day]),
             critical_quotes=sorted((r for r in quotes[day] if r['topic']==5),key=lambda r:(-(r['severity_score'] or 0),r['ts']))[:10],
             reaction_topics=rank(meme_episodes,day,None) if meme_states.get(day)=='reviewed' else highlights(quotes[day],channel,2),
             meme_review={'status':meme_states.get(day,'not_reviewed')}))
        total=[a+b for a,b in zip(total,data['vector'])]
    calendar=calendar_index(days,dt.date.fromisoformat(observed[0]),dt.date.fromisoformat(observed[-1]))
    selection=read(root/'selection.json')
    payload=dict(schema_version=4,as_of=observed[-1],generated_at=generated,min_date=observed[0],
        default_date=observed[-1],first_observed=observed[0],last_observed=observed[-1],observed_days=len(observed),
        topics=TOPICS,tones=SENTIMENTS,totals=totals(total),calendar=calendar,channel=channel,
        source={'channel_url':channel['source_url'],'catalogue_sessions':len(read(root/'catalogue.json')['data']['lives']),
                'processed_sessions':len(lives),'unavailable_sources':[]},
        live_only=True,daily_insights=True,insights_generated_at=generated,
        classification_status={'unprocessed':info['pending_texts'],'unknown_events':info['topic_counts'].get(6,0),
                               'unreadable_events':info['unreadable_events']},
        selection=selection,method='字面括号规则 + 模型分类 + 独立措辞强度；升级保留既有分类与评分',
        coverage_note='仅统计来源已收录且已结束的直播区间；缺档不代表没有开播。模型分类未经逐条人工核验。图片及缺失正文归待判断。玩梗以SC或同传文本为依据，不能证明主播音视频内容；尚未审核的旧日仅显示原文频次。',
        schedule={k:v for k,v in (read(root/'schedule.json') if (root/'schedule.json').exists() else {'enabled':False}).items()
                  if k in ('enabled','timezone','hour','minute','poll_seconds')},
        sessions=[{k:live.get(k) for k in ('liveId','title','startDate','stopDate','isFull','danmakusCount')} for live in lives.values()])
    save(site/'data.json',payload)
    # This report is explicitly aggregated; raw records, authors and local paths stay private.
    save(site/'report.json',dict(channel=channel,selection=selection,generated_at=generated,events=info['events'],
                               topics=TOPICS,topic_counts=info['topic_counts'],unreadable_events=info['unreadable_events'],
                               source_counts=dict(exclusions),coverage_note=payload['coverage_note']))
    embed(site)
    for path in list(site.rglob('*')):
        if path.is_file() and path.suffix in ('.json','.html','.css','.js','.svg'):
            Path(str(path)+'.gz').write_bytes(gzip.compress(path.read_bytes(),compresslevel=9,mtime=0))
    validate(site)
    # Serve an immutable release via one small atomically replaced pointer file.
    release=root/'releases'/dt.datetime.now(TZ).strftime('%Y%m%d-%H%M%S-%f')
    release.parent.mkdir(exist_ok=True);site.rename(release)
    save(root/'current.json',{'directory':str(release),'generated_at':generated})
    return release

def validate(site):
    site=Path(site);data=read(site/'data.json');total=0
    for day,entry in data['calendar'].items():
        if not entry['observed']:continue
        d=read(site/'days'/f'{day}.json');insight=read(site/'insights'/f'{day}.json')
        counts=d['series']['all'];total+=counts['total']
        if counts!=entry['series']['all'] or counts['total']!=sum(counts['topic']):raise ValueError('Daily classification count mismatch')
        if sum(p['critical_total_count'] for p in insight['period_insights'])!=counts['topic'][5]:raise ValueError('Attack period count mismatch')
        for p in insight['period_insights']:
            if any(r['topic']!=5 or not p['start']<=r['ts']<p['end'] for r in p['critical_quotes']):raise ValueError('Invalid attack excerpt')
    if total!=data['totals']['all']['total']:raise ValueError('Site total mismatch')
    return dict(events=total,days=data['observed_days'])
