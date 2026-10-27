"""Private R2 checkpoint for disposable hosted runners, with a consistent SQLite copy."""
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path
from .util import read,save

class CloudState:
    def __init__(self,uid,client=None,bucket=None):
        if not str(uid).isdigit():raise ValueError('YOUR_LIVE_EYE_UID must be a numeric resolved UP UID')
        self.uid=int(uid);self.bucket=bucket or os.environ['YOUR_LIVE_EYE_STATE_BUCKET']
        self.key=f'your-live-eye/{self.uid}/state.tar.gz'
        if client is None:
            import boto3
            client=boto3.client('s3',endpoint_url='https://'+os.environ['CLOUDFLARE_ACCOUNT_ID']+'.r2.cloudflarestorage.com',
                aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],region_name='auto')
        self.client=client

    def restore(self,root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir='/tmp/codextmp') as tmp:
            archive=Path(tmp)/'state.tar.gz'
            try:self.client.download_file(self.bucket,self.key,str(archive))
            except Exception as error:
                code=getattr(error,'response',{}).get('Error',{}).get('Code')
                if str(code) in ('404','NoSuchKey','NotFound'):return False
                raise  # Permission/network failures must not silently start a new paid analysis.
            with tarfile.open(archive,'r:gz') as tar:
                for member in tar.getmembers():
                    path=Path(member.name)
                    if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                        raise ValueError('Unsafe checkpoint member')
                tar.extractall(root,filter='data')
        config=read(root/'config.json')
        if config['channel']['uid']!=self.uid:raise ValueError('Checkpoint belongs to another streamer')
        if (root/'current.json').exists():
            current=read(root/'current.json');current['directory']=str(root/'releases'/Path(current['directory']).name)
            save(root/'current.json',current)
        return True

    def save(self,root):
        root=Path(root)
        if not (root/'config.json').exists():return
        with tempfile.TemporaryDirectory(dir='/tmp/codextmp') as tmp:
            tmp=Path(tmp);archive=tmp/'state.tar.gz';database=root/'analysis.sqlite'
            if database.exists():
                with closing(sqlite3.connect(database)) as source,closing(sqlite3.connect(tmp/'analysis.sqlite')) as dest:source.backup(dest)
            current=Path(read(root/'current.json')['directory']).name if (root/'current.json').exists() else None
            with tarfile.open(archive,'w:gz',compresslevel=1) as tar:
                for path in sorted(root.rglob('*')):
                    relative=path.relative_to(root)
                    allowed_dirs={'raw','prompts','attempts','releases','memes'}
                    allowed_files={'config.json','catalogue.json','selection.json','coverage.json','progress.json','last-run.json','checkpoint.json','scheduler-state.json','current.json'}
                    if relative.parts[0] not in allowed_dirs and str(relative) not in allowed_files:continue
                    if not path.is_file() or path.is_symlink():continue
                    if any(p.startswith('._') or p=='__pycache__' for p in relative.parts):continue
                    if relative.parts[0] in ('logs',) or path.name in ('stop-claim','analysis.sqlite','analysis.sqlite-wal','analysis.sqlite-shm'):continue
                    if path.name.endswith(('.lock','.tmp')):continue
                    if relative.parts[0]=='releases' and (len(relative.parts)<2 or relative.parts[1]!=current):continue
                    tar.add(path,arcname=str(relative),recursive=False)
                if database.exists():tar.add(tmp/'analysis.sqlite',arcname='analysis.sqlite')
            # Multipart completion replaces this object atomically; failed uploads
            # leave the prior successful checkpoint available.
            self.client.upload_file(str(archive),self.bucket,self.key)
