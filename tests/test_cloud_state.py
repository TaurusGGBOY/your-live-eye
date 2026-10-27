import io
import json
import shutil
import tarfile
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from your_live_eye.cloud_state import CloudState
from your_live_eye import checkpoint
from your_live_eye.store import connect
from your_live_eye.util import read,save

class Missing(Exception):
    response={'Error':{'Code':'NoSuchKey'}}

class ObjectStore:
    def __init__(self):self.data=None
    def download_file(self,bucket,key,path):
        if self.data is None:raise Missing()
        Path(path).write_bytes(self.data)
    def upload_file(self,path,bucket,key):self.data=Path(path).read_bytes()

class CloudStateTests(unittest.TestCase):
    def setUp(self):
        Path('/tmp/codextmp').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir='/tmp/codextmp');self.base=Path(self.temp.name)
    def tearDown(self):checkpoint.configure();self.temp.cleanup()

    def test_private_roundtrip_survives_new_runner_and_keeps_sqlite(self):
        root=self.base/'old-runner';root.mkdir();store=ObjectStore();cloud=CloudState(123,store,'private-test')
        self.assertFalse(cloud.restore(root))
        save(root/'config.json',{'channel':{'uid':123}})
        save(root/'current.json',{'directory':str(root/'releases/current')})
        save(root/'releases/current/data.json',{'value':1})
        save(root/'releases/old/data.json',{'value':0})
        (root/'raw/stream').mkdir(parents=True);(root/'raw/stream/body').write_text('source', encoding='utf-8')
        (root/'.env').write_text('should not leave the machine', encoding='utf-8')
        with closing(connect(root)) as db,db:
            db.execute("INSERT INTO texts(text,kind,topic) VALUES('saved work','SC',4)")
        cloud.save(root)
        # Restore into a different filesystem root; sqlite WAL is represented in backup.
        target=self.base/'next-runner';self.assertTrue(cloud.restore(target))
        with closing(connect(target)) as db:self.assertEqual(db.execute('SELECT text FROM texts').fetchone()[0],'saved work')
        self.assertEqual(read(target/'current.json')['directory'],str(target/'releases/current'))
        self.assertTrue((target/'raw/stream/body').exists())
        self.assertFalse((target/'.env').exists());self.assertFalse((target/'releases/old').exists())

    def test_permission_error_is_not_a_new_empty_dataset(self):
        store=ObjectStore();cloud=CloudState(123,store,'test')
        with patch.object(store,'download_file',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):cloud.restore(self.base/'restore')

    def test_archive_traversal_rejected(self):
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as tar:
            info=tarfile.TarInfo('../outside');info.size=3;tar.addfile(info,io.BytesIO(b'bad'))
        store=ObjectStore();store.data=buffer.getvalue()
        with self.assertRaises(ValueError):CloudState(123,store,'test').restore(self.base/'restore')
        self.assertFalse((self.base/'outside').exists())

    def test_boundary_saves_then_stops_before_hosted_limit(self):
        called=[]
        with patch('your_live_eye.checkpoint.time.monotonic',return_value=100):checkpoint.configure(called.append,max_seconds=10)
        with patch('your_live_eye.checkpoint.time.monotonic',return_value=101):checkpoint.boundary(self.base)
        with patch('your_live_eye.checkpoint.time.monotonic',return_value=102):checkpoint.boundary(self.base)
        self.assertEqual(called,[self.base])
        with patch('your_live_eye.checkpoint.time.monotonic',return_value=111):
            with self.assertRaises(TimeoutError):checkpoint.boundary(self.base)
        self.assertEqual(called,[self.base,self.base])

if __name__=='__main__':unittest.main()
