import contextlib
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')

def default_state():
    if os.environ.get('YOUR_LIVE_EYE_STATE'):return Path(os.environ['YOUR_LIVE_EYE_STATE']).expanduser()
    if sys.platform=='darwin':return Path.home()/'Library/Application Support/YourLiveEye'
    if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'YourLiveEye'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'your_live_eye'

def now():
    return dt.datetime.now(TZ).isoformat()

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def log(event, **fields):
    print(json.dumps(dict(time=now(), event=event, **fields), ensure_ascii=True), flush=True)

@contextlib.contextmanager
def process_lock(path):
    """Reuse OS process locks so a scheduled refresh cannot race a manual run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b'0'); stream.flush(); stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
