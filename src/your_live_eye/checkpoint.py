"""Optional cloud checkpoint at completed source/batch boundaries."""
import threading
import time
from .util import log

_save=None
_next=0
_deadline=float('inf')
_mutex=threading.Lock()

def configure(save=None,max_seconds=16200):
    global _save,_next,_deadline
    _save=save;_next=0;_deadline=time.monotonic()+max_seconds if save else float('inf')

def boundary(root):
    global _next
    if _save is None:return
    if not _mutex.acquire(blocking=False):return
    try:
        clock=time.monotonic()
        if clock>=_next or clock>=_deadline:
            _save(root);_next=time.monotonic()+900
            log('cloud_checkpoint_saved')
        if clock>=_deadline:
            raise TimeoutError('Hosted work window reached; progress saved. Next update continues this state.')
    finally:_mutex.release()
