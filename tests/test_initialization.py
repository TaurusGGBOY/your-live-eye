import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from your_live_eye.classifier import classify
from your_live_eye.cli import main
from your_live_eye.cloudflare import prepare
from your_live_eye.pipeline import run
from your_live_eye.schedule import due_date,tick
from your_live_eye.source import Source,select_sessions
from your_live_eye.store import summary
from your_live_eye.util import TZ,read,save
from test_pipeline import CHANNEL,SETTINGS

BASE=int(dt.datetime(2026,1,2,tzinfo=TZ).timestamp()*1000)
def live(name,day=0,finished=True):
    return dict(liveId=name,startDate=BASE+day*86400000,stopDate=BASE+day*86400000+600000,
                isFinish=finished,danmakusCount=1,title=name)

class InitializationTests(unittest.TestCase):
    def setUp(self):
        Path('/tmp/codextmp').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='/tmp/codextmp');self.root=Path(self.temp.name)
        self.config=dict(channel=CHANNEL,model=SETTINGS,deploy=False,source_base='https://example.invalid',
                         date='all',fallback_latest=False,timezone='Asia/Shanghai',update_at='04:00')
        save(self.root/'config.json',self.config)
        self.acquired=[]

    def tearDown(self):self.temp.cleanup()

    def acquire(self,item,*args):
        self.acquired.append(item['liveId'])
        return [dict(live_id=item['liveId'],source_row=1,timestamp_ms=item['startDate']+1000,
                     event_type='SC' if item['liveId']=='late' else 'Message',payload_kind=0,payload=[item['liveId']])]

    @staticmethod
    def caller(rows,prompt,settings,stem):
        return {r['id']:4 for r in rows},dict(error=None,seconds=.01,usage={},output_path=str(stem))

    def execute(self,lives,acquire=None):
        with patch.object(Source,'catalogue',return_value={'channel':CHANNEL,'lives':lives}), \
             patch.object(Source,'acquire',side_effect=acquire or self.acquire), \
             patch('your_live_eye.memes.update',return_value={'status':'complete'}), \
             patch('your_live_eye.pipeline.classify',side_effect=lambda root,settings,channel:classify(root,settings,channel,self.caller)):
            return run(self.root/'config.json')

    def test_default_all_and_late_old_archive_not_limited_by_checkpoint(self):
        first=live('first');last=live('last',2);ongoing=live('ongoing',3,False)
        future=live('future',5000)
        selected,selection=select_sessions({'lives':[first,last,ongoing,future]})
        self.assertEqual({x['liveId'] for x in selected},{'first','last'})
        self.assertEqual(selection['deferred_sessions'],2)
        self.execute([first,last,ongoing,future])
        self.assertEqual(self.acquired,['first','last']);attempts=summary(self.root)['model_attempts']
        # Older than the original earliest checkpoint, plus the previously ongoing stream.
        self.acquired=[]
        self.execute([first,last,live('late',-30),dict(ongoing,isFinish=True),future])
        self.assertEqual(self.acquired,['late','ongoing'])
        self.assertEqual(summary(self.root)['events'],4)
        self.assertEqual(read(self.root/'coverage.json')['imported'],4)
        self.assertEqual(read(self.root/'checkpoint.json')['earliest_start'],live('late',-30)['startDate'])
        self.acquired=[];self.execute([first,last,live('late',-30),dict(ongoing,isFinish=True),future])
        self.assertEqual(self.acquired,[])
        self.assertEqual(summary(self.root)['model_attempts'],attempts+1)

    def test_failed_source_keeps_other_progress_and_resumes_missing(self):
        first=live('first');bad=live('bad',1);last=live('last',2)
        def acquire(item,*args):
            if item['liveId']=='bad':raise RuntimeError('temporary archive failure')
            return self.acquire(item,*args)
        with self.assertRaisesRegex(RuntimeError,'source downloads incomplete'):
            self.execute([first,bad,last],acquire)
        self.assertEqual(self.acquired,['first','last'])
        self.assertFalse((self.root/'current.json').exists())
        self.assertFalse((self.root/'checkpoint.json').exists())
        self.assertEqual(summary(self.root)['pending_texts'],0)
        self.acquired=[];self.execute([first,bad,last])
        self.assertEqual(self.acquired,['bad']);self.assertEqual(summary(self.root)['events'],3)

    def test_cli_requires_explicit_demo_and_can_configure_without_models(self):
        for flag,scope in [([], 'all'),(['--demo'],'latest')]:
            state=self.root/scope
            with patch.object(Source,'resolve',return_value=(CHANNEL,{})), \
                 patch('sys.argv',['your-live-eye','run','123','--state',str(state),'--configure-only']+flag), \
                 patch('your_live_eye.pipeline.run') as pipeline:
                main();pipeline.assert_not_called()
            self.assertEqual(read(state/'123/config.json')['date'],scope)
            self.assertFalse((state/'123/analysis.sqlite').exists())

    def test_daily_failed_retry_is_bounded_and_next_day_retries(self):
        save(self.root/'scheduler-state.json',{'last_success_due_date':'2026-01-01'})
        with patch('your_live_eye.schedule.due_date',return_value='2026-01-02'), \
             patch('your_live_eye.pipeline.run',side_effect=RuntimeError('model unavailable')) as pipeline:
            with self.assertRaises(RuntimeError):tick(self.root/'config.json')
            self.assertEqual(tick(self.root/'config.json')['status'],'retry_next_day')
            pipeline.assert_called_once_with((self.root/'config.json').resolve(),retry_failed=True)
        self.assertEqual(read(self.root/'scheduler-state.json')['last_success_due_date'],'2026-01-01')
        with patch('your_live_eye.schedule.due_date',return_value='2026-01-03'), \
             patch('your_live_eye.pipeline.run',return_value={'status':'success'}):
            self.assertEqual(tick(self.root/'config.json')['status'],'updated')
            self.assertEqual(tick(self.root/'config.json')['status'],'up_to_date')

    def test_schedule_timezone_and_busy_does_not_consume_attempt(self):
        clock=dt.datetime(2026,10,27,9,29,tzinfo=dt.timezone.utc)
        config={'timezone':'Asia/Tokyo','update_at':'18:30'}
        self.assertEqual(due_date(clock,config),'2026-10-26')
        self.assertEqual(due_date(clock+dt.timedelta(minutes=1),config),'2026-10-27')
        with patch('your_live_eye.pipeline.run',side_effect=BlockingIOError):
            self.assertEqual(tick(self.root/'config.json')['status'],'busy')
        self.assertNotIn('last_attempt_due_date',read(self.root/'scheduler-state.json'))

    def test_cloudflare_exports_only_completed_static_site(self):
        with self.assertRaisesRegex(RuntimeError,'Complete initialization'):
            prepare(self.root/'config.json',self.root/'export')
        self.execute([live('first'),live('last',2)])
        result=prepare(self.root/'config.json',self.root/'export')
        self.assertTrue(result['ready'])
        self.assertTrue((self.root/'export/index.html').exists())
        self.assertFalse((self.root/'export/analysis.sqlite').exists())
        self.assertFalse((self.root/'export/config.json').exists())
        with patch('your_live_eye.schedule.tick',return_value={'status':'retry_next_day'}):
            result=prepare(self.root/'config.json',self.root/'not-exported','scheduled')
        self.assertFalse(result['ready']);self.assertFalse((self.root/'not-exported').exists())

if __name__=='__main__':unittest.main()
