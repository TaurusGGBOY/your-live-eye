import datetime as dt
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import msgpack

from your_live_eye.source import decode,Source,SourceError,select_sessions
from your_live_eye.store import connect,ingest,summary
from your_live_eye.classifier import classify
from your_live_eye.validation import salvage_pairs,salvage_scored
from your_live_eye.schedule import due_date,tick
from your_live_eye.site import build,validate
from your_live_eye.util import TZ,save

CHANNEL={'uid':123,'room_id':456,'name':'测试 <主播>', 'live_url':'https://live.bilibili.com/456',
         'profile_url':'https://space.bilibili.com/123','source_url':'https://danmakus.com/channel/123'}
START=int(dt.datetime(2026,10,25,23,58,tzinfo=TZ).timestamp()*1000)
LIVE={'liveId':'test-live','startDate':START,'stopDate':START+600000,'isFinish':True,'danmakusCount':6,'title':'test'}
SETTINGS=dict(provider='codex',model='test',reasoning='high',tier='fast',batch_size=2,
              batch_bytes=200000,review_batch_size=2,concurrency=2,max_attempts=3,timeout=60)

def event(index,text,ts=None,kind='Message',payload_kind=0):
    return dict(source_row=index,live_id=LIVE['liveId'],timestamp_ms=ts or START+index*1000,
                event_type=kind,payload=[text],payload_kind=payload_kind)

class SourceTests(unittest.TestCase):
    def test_decode_identity_and_delta(self):
        raw=msgpack.packb([[123,'test',456],[],[START,[],[],[[1000,0,0,0,0,['hi']],[2000,3,0,0,0,['SC']]]]])
        _,rows=decode('test',raw,CHANNEL)
        self.assertEqual([r['timestamp_ms'] for r in rows],[START+1000,START+3000])
        self.assertEqual(rows[1]['event_type'],'SC')
        with self.assertRaises(SourceError):decode('test',raw,dict(CHANNEL,uid=124))

    def test_latest_and_cross_midnight(self):
        live=LIVE.copy();unfinished=dict(live,liveId='ongoing',startDate=START+999999,isFinish=False)
        clock=dt.datetime(2026,10,27,tzinfo=TZ)
        selected,_=select_sessions({'lives':[live,unfinished]},'2026-10-26',clock=clock)
        self.assertEqual(selected,[live])
        with self.assertRaises(SourceError):select_sessions({'lives':[live]},'2026-10-24',clock=clock)
        selected,note=select_sessions({'lives':[live]},'2026-10-24',True,clock)
        self.assertEqual(note['selection'],'latest_finished_fallback')

    def test_nickname_ambiguity_and_uid(self):
        source=Source()
        with patch.object(source,'api',return_value={'data':[{'uName':'same','uId':1},{'uName':'same','uId':2}]}):
            with self.assertRaises(SourceError):source.resolve('same')
        with patch.object(source,'catalogue',return_value={'channel':{'uId':123,'roomId':456,'uName':'test'},'lives':[]}) as catalogue:
            self.assertEqual(source.resolve('https://space.bilibili.com/123')[0]['uid'],123)
            catalogue.assert_called_once_with(123)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        Path('/tmp/codextmp').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='/tmp/codextmp');self.root=Path(self.temp.name)
        save(self.root/'catalogue.json',{'data':{'lives':[LIVE]}})
        save(self.root/'selection.json',{'selection':'latest_finished'})
        self.config=dict(channel=CHANNEL,model=SETTINGS,deploy=False)
        save(self.root/'config.json',self.config)
    def tearDown(self):self.temp.cleanup()

    @staticmethod
    def caller(rows,prompt,settings,stem):
        labels={r['id']:5 if r['text']=='指责' and 'contexts' not in r else 4 for r in rows}
        if settings.get('response_kind')=='scored_review':labels={cid:{'topic':topic,'severity_score':0} for cid,topic in labels.items()}
        return labels,dict(error=None,seconds=.01,usage={'input_tokens':10},output_path=str(stem)+'.json')

    def test_exact_text_counts_rule_and_rebuild(self):
        rows=[event(1,'你好'),event(2,'你好',kind='SC'),event(3,'【只有左'),event(4,'指责'),
              event(5,42,payload_kind=2),event(6,'下播后',LIVE['stopDate']+1),event(7,'跨天',START+180000)]
        counts=ingest(self.root,LIVE,rows);self.assertEqual(counts['after_stop'],1)
        classify(self.root,SETTINGS,CHANNEL,self.caller)
        state=summary(self.root);self.assertEqual(state['events'],6);self.assertEqual(state['unique_texts'],4)
        self.assertEqual(state['topic_counts'][0],1);self.assertEqual(state['pending_texts'],0)
        # Ordinary criticism candidate is removed by second stage; unknown image survives.
        self.assertNotIn(5,state['topic_counts']);self.assertEqual(state['unreadable_events'],1)
        attempts=state['model_attempts']
        ingest(self.root,LIVE,rows);classify(self.root,SETTINGS,CHANNEL,self.caller)
        self.assertEqual(summary(self.root)['model_attempts'],attempts)
        save(self.root/'schedule.json',{'enabled':True,'hour':4,'command':['private-runtime',str(self.root)],'path':str(self.root)})
        site=build(self.root,self.config)
        self.assertEqual(validate(site)['events'],6)
        self.assertEqual(validate(site)['days'],2)
        html=(site/'index.html').read_text();self.assertIn('测试 &lt;主播&gt;',html)
        self.assertNotIn('火羽',html);self.assertNotIn('2094031249',html)
        for path in site.rglob('*.json'):
            value=path.read_text();self.assertNotIn('user_id',value);self.assertNotIn(str(self.root),value)

    def test_strength_preserves_counts_and_reuses_scores(self):
        ingest(self.root,LIVE,[event(1,'攻击甲'),event(2,'攻击甲'),event(3,'攻击乙')])
        def caller(rows,prompt,settings,stem):
            score=settings.get('max_output_value')==100
            values={r['id']:(75 if r['text']=='攻击甲' else 0) if score else 5 for r in rows}
            if settings.get('response_kind')=='scored_review':values={r['id']:{'topic':5,'severity_score':75 if r['text']=='攻击甲' else 0} for r in rows}
            return values,dict(error=None,seconds=.01,usage={},output_path=str(stem))
        classify(self.root,SETTINGS,CHANNEL,caller)
        state=summary(self.root)
        self.assertEqual(state['topic_counts'][5],3);self.assertEqual(state['pending_scores'],0)
        self.assertEqual(state['model_attempts'],2) # One primary + one combined review, no separate scoring call.
        site=build(self.root,self.config)
        insights=json.loads((site/'insights/2026-10-25.json').read_text())
        self.assertEqual([r['severity_score'] for r in insights['critical_quotes']],[75,75,None])
        classify(self.root,SETTINGS,CHANNEL,caller)
        self.assertEqual(summary(self.root)['model_attempts'],state['model_attempts'])
        # A score is not a category; reject out-of-range values without rejecting valid IDs.
        values,audit=salvage_pairs({'items':[[1,75],[2,101],[3,0]]},[{'content_id':x} for x in (1,2,3)],100)
        self.assertEqual(values,{1:75,3:0});self.assertEqual(audit['missing_ids'],[2])
        values,audit=salvage_scored({'items':[[1,5,75],[2,4,90],[3,5,101],[4,4,0]]},[{'content_id':x} for x in (1,2,3,4)])
        self.assertEqual(values,{1:{'topic':5,'severity_score':75},4:{'topic':4,'severity_score':0}})
        self.assertEqual(audit['missing_ids'],[2,3])

    def test_partial_retry_only_missing(self):
        ingest(self.root,LIVE,[event(1,'a'),event(2,'b')]);seen=[]
        def caller(rows,prompt,settings,stem):
            seen.append([r['id'] for r in rows])
            labels={rows[0]['id']:4} if len(seen)==1 else {r['id']:4 for r in rows}
            return labels,dict(error=None,seconds=.01,usage={},output_path=str(stem))
        with patch('your_live_eye.classifier.time.sleep'):
            classify(self.root,SETTINGS,CHANNEL,caller)
        self.assertEqual([len(x) for x in seen],[2,1]);self.assertNotIn(seen[0][0],seen[1])

    def test_failed_model_not_published(self):
        ingest(self.root,LIVE,[event(1,'hi')])
        def failure(*args):return {},dict(error='test_failure',seconds=.01,usage={},output_path='test')
        with patch('your_live_eye.classifier.time.sleep'):
            with self.assertRaises(RuntimeError):classify(self.root,dict(SETTINGS,max_attempts=1),CHANNEL,failure)
        with self.assertRaises(RuntimeError):build(self.root,self.config)
        self.assertFalse((self.root/'current.json').exists())

    def test_salvage_rejects_duplicate_or_foreign(self):
        labels,audit=salvage_pairs({'items':[[1,4],[1,5],[2,3],[99,1],[3,8]]},[{'content_id':x} for x in (1,2,3)])
        self.assertEqual(labels,{2:3});self.assertEqual(audit['missing_ids'],[1,3])

    def test_scheduler_shanghai_and_failed_checkpoint(self):
        self.assertEqual(due_date(dt.datetime(2026,10,27,3,59,tzinfo=TZ)),'2026-10-26')
        self.assertEqual(due_date(dt.datetime(2026,10,27,4,0,tzinfo=TZ)),'2026-10-27')
        save(self.root/'scheduler-state.json',{'last_success_due_date':'2020-01-01'})
        with patch('your_live_eye.pipeline.run',side_effect=RuntimeError('source failed')):
            with self.assertRaises(RuntimeError):tick(self.root/'config.json')
        self.assertEqual(json.loads((self.root/'scheduler-state.json').read_text())['last_success_due_date'],'2020-01-01')

if __name__=='__main__':unittest.main()
