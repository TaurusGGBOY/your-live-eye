import copy
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from your_live_eye import memes
from your_live_eye.classifier import classify,queue,prompt_for
from your_live_eye.provider import call
from your_live_eye.store import connect,ingest,summary
from your_live_eye.util import read,save
from test_pipeline import CHANNEL,SETTINGS,LIVE,START,event

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        Path('/tmp/codextmp').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='/tmp/codextmp');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_upgrade_preserves_old_decisions_and_stops_reclassifying(self):
        ingest(self.root,LIVE,[event(1,'保留低分'),event(2,'旧已复核闲聊'),event(3,'旧未复核'),event(4,'新原文')])
        with closing(connect(self.root)) as db,db:
            db.execute("UPDATE texts SET candidate_topic=5,topic=5,severity_score=7 WHERE id=1")
            db.execute("UPDATE texts SET candidate_topic=5,topic=4,severity_score=0 WHERE id=2")
            db.execute("UPDATE texts SET candidate_topic=5 WHERE id=3")
        queue(self.root,'review_scored',SETTINGS)
        seen=[]
        def caller(rows,prompt,settings,stem):
            seen.append(([r['id'] for r in rows],Path(stem).name))
            return {r['id']:9 if settings.get('min_output_value')==1 else 5 for r in rows},dict(error=None,seconds=.1,usage={},output_path=str(stem))
        classify(self.root,SETTINGS,CHANNEL,caller)
        with closing(connect(self.root)) as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT id,topic,severity_score FROM texts ORDER BY id')],[(1,5,7),(2,4,0),(3,5,9),(4,5,9)])
            self.assertEqual(db.execute("SELECT status FROM batches WHERE stage='review_scored'").fetchone()[0],'superseded')
        self.assertTrue(all(1 not in ids and 2 not in ids and 'review' not in name for ids,name in seen))
        classify(self.root,SETTINGS,CHANNEL,caller);self.assertEqual(len(seen),2)

    def test_legacy_primary_resumes_without_enqueuing_new_text(self):
        ingest(self.root,LIVE,[event(1,'旧队列')]);queue(self.root,'primary',SETTINGS)
        (self.root/'prompts').mkdir();(self.root/'prompts/primary.txt').write_text(prompt_for('primary',CHANNEL),encoding='utf-8')
        ingest(self.root,LIVE,[event(1,'旧队列'),event(2,'新加入')]);calls=[]
        def caller(rows,prompt,settings,stem):
            calls.append((Path(stem).name,[r['id'] for r in rows]))
            return {r['id']:4 for r in rows},dict(error=None,seconds=.1,usage={},output_path=str(stem))
        classify(self.root,SETTINGS,CHANNEL,caller)
        self.assertEqual(calls[0][1],[1]);self.assertEqual(calls[1][1],[2]);self.assertTrue(calls[1][0].startswith('primary_quarrel'))

    def test_intensity_parser_rejects_reclassification_zero_duplicate_and_unknown(self):
        payload={'items':[[1,8],[2,5,20],[3,0],[4,101],[5,20],[5,30],[99,30]]}
        metrics=dict(error=None,seconds=.1,usage={},output_path='test')
        with patch('your_live_eye.provider.request',return_value=(payload,metrics)):
            labels,metrics=call([{'id':n} for n in range(1,6)],'',dict(SETTINGS,max_output_value=100,min_output_value=1),self.root/'attempt')
        self.assertEqual(labels,{1:8});self.assertEqual(metrics['audit']['missing_ids'],[2,3,4,5])

class MemeTests(unittest.TestCase):
    def setUp(self):
        Path('/tmp/codextmp').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='/tmp/codextmp');self.root=Path(self.temp.name);self.calls=[]
        self.config=dict(channel=CHANNEL,model=dict(SETTINGS,max_attempts=1))
        self.rows=[event(1,'给主播一个求婚申请',kind='SC'),event(2,'【拒绝结婚申请】'),event(3,'光速拒绝'),event(4,'光速拒绝')]
        ingest(self.root,LIVE,self.rows)

    def tearDown(self):self.temp.cleanup()

    def caller(self,packet,prompt,settings,stem,schema):
        self.calls.append(str(stem))
        if 'windows' in packet:
            result={'windows':[dict(id=w['id'],status='reviewed',reason='有对应原文',episodes=[dict(key='光速拒绝',title='求婚被秒拒',overview='SC求婚后，同传记录拒绝，观众接话。',first_row=3,last_row=4,reply_groups=[3],evidence_rows=[1,2,3],sc_row=1,status='sc_supported')]) for w in packet['windows']]}
        else:result={'items':[dict(id=r['id'],decision='accept',reason='原文支持') for r in packet['items']]}
        return result,dict(error=None,seconds=.1,usage={},output_path=str(stem))

    def test_actual_input_changes_rereview_and_identical_input_reuses(self):
        memes.update(self.root,self.config,self.caller);self.assertEqual(len(self.calls),2)
        ingest(self.root,dict(LIVE,title='仅目录标题改变'),self.rows)
        self.assertEqual(memes.update(self.root,self.config,self.caller)['status'],'reused');self.assertEqual(len(self.calls),2)
        self.rows[0]['payload']=['修改后的求婚SC'];ingest(self.root,LIVE,self.rows)
        memes.update(self.root,self.config,self.caller);self.assertEqual(len(self.calls),4)
        accepted,states=memes.load(self.root);self.assertEqual(states['2026-10-25'],'reviewed')
        ranked=memes.rank(accepted,'2026-10-25',2);self.assertEqual(ranked[0]['reaction_count'],2)
        self.assertEqual(ranked[0]['related_sc']['text'],'修改后的求婚SC')

    def test_failed_secondary_keeps_previous_accepted_and_retries_only_secondary(self):
        memes.update(self.root,self.config,self.caller);before=read(self.root/'memes/index.json')[LIVE['liveId']]['published']
        self.rows[0]['payload']=['另一条SC'];ingest(self.root,LIVE,self.rows)
        def failing(packet,*args):
            if 'items' in packet:return None,dict(error='unavailable')
            return self.caller(packet,*args)
        with self.assertRaises(RuntimeError):memes.update(self.root,self.config,failing)
        state=read(self.root/'memes/index.json')[LIVE['liveId']];self.assertEqual(state['published'],before)
        self.assertEqual(memes.load(self.root)[1]['2026-10-25'],'not_reviewed')
        count=len(self.calls);memes.update(self.root,self.config,self.caller,retry_failed=True)
        self.assertEqual(len(self.calls),count+1);self.assertIn('secondary',self.calls[-1])

    def test_reject_future_sc_foreign_groups_and_missing_translation(self):
        packet=memes.packets(next(memes.sources(self.root))[1],200000)[0]
        result,_=self.caller(packet,'',SETTINGS,self.root/'none',{})
        episode=result['windows'][0]['episodes'][0];window=packet['windows'][0]
        for bad in (dict(episode,reply_groups=[999]),dict(episode,status='translation_supported',sc_row=0,evidence_rows=[1,3])):
            with self.assertRaises((ValueError,KeyError)):memes.materialize(window,bad,LIVE['liveId'])
        future=copy.deepcopy(window);future['sc'][0]['ts']=START+100000
        with self.assertRaisesRegex(ValueError,'Future'):memes.materialize(future,episode,LIVE['liveId'])

    def test_reject_missing_window_and_secondary_ids(self):
        packet=memes.packets(next(memes.sources(self.root))[1],200000)[0]
        with self.assertRaises(ValueError):memes.validate_primary({'windows':[]},packet,LIVE['liveId'])
        with self.assertRaises(ValueError):memes.validate_secondary({'items':[]},[{}])

    def test_all_day_keeps_more_than_two_topics_period_still_one(self):
        memes.update(self.root,self.config,self.caller)
        item=memes.load(self.root)[0][0]
        items=[dict(item,meme_key=f'test-{n}') for n in range(4)]
        self.assertEqual(len(memes.rank(items,'2026-10-25',None)),4)
        self.assertEqual(len(memes.rank(items,'2026-10-25',1,(START,START+60000))),1)

    def test_occurrence_alias_is_exact_and_raw_receipt_is_recoverable(self):
        packet=memes.packets(next(memes.sources(self.root))[1],200000)[0]
        payload,metrics=self.caller(packet,'',SETTINGS,self.root/'none',{})
        payload['windows'][0]['episodes'][0]['reply_groups']=[4]
        self.assertEqual(len(memes.validate_primary(payload,packet,LIVE['liveId'])),1)
        folder=self.root/'memes/runs/1/chunks/0'
        save(folder/'primary.json',{'attempts':3,'status':'failed'})
        save(folder/'attempts/primary-3.json',payload);save(folder/'attempts/primary-3.metrics.json',{'error':None})
        def no_call(*args):raise AssertionError('Do not repeat inference for a valid saved response')
        result=memes.phase(folder,'primary',packet,'',SETTINGS,memes.PRIMARY,
            lambda p:memes.validate_primary(p,packet,LIVE['liveId']),no_call,False)
        self.assertEqual(len(result),1);self.assertEqual(read(folder/'primary.json')['recovered_attempt'],3)
        self.assertEqual(read(folder/'attempts/primary-3.json'),payload)

    def test_failed_meme_review_does_not_publish_or_advance_pipeline(self):
        from your_live_eye.pipeline import run
        from your_live_eye.source import Source
        config=dict(self.config,source_base='https://example.invalid',date='all',deploy=False)
        save(self.root/'config.json',config);save(self.root/'checkpoint.json',{'earliest_start':START,'last_success_at':'unchanged'})
        with patch.object(Source,'catalogue',return_value={'lives':[LIVE]}),patch.object(Source,'acquire',return_value=self.rows),patch('your_live_eye.pipeline.classify'),patch('your_live_eye.memes.update',side_effect=RuntimeError('review failed')):
            with self.assertRaises(RuntimeError):run(self.root/'config.json')
        self.assertEqual(read(self.root/'checkpoint.json')['last_success_at'],'unchanged');self.assertFalse((self.root/'current.json').exists())

if __name__=='__main__':unittest.main()
