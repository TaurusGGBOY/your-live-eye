"""Prepare a fresh static export for the Cloudflare Action; never upload private state."""
from pathlib import Path
from .util import read

def prepare(config_path,output,mode='publish'):
    config_path=Path(config_path).resolve();config=read(config_path);root=config_path.parent
    if mode=='scheduled':
        from .schedule import tick
        result=tick(config_path)
        if result['status'] not in ('updated','up_to_date'):
            return dict(ready=False,update=result)
    elif mode=='update':
        from .pipeline import run
        result=run(config_path,retry_failed=True)
    elif mode=='publish':
        result={'status':'export_existing'}
    else:raise ValueError('Unknown Cloudflare build mode')
    # Publish-only must not turn a partially imported dataset into a complete site.
    if not (root/'last-run.json').exists() or read(root/'last-run.json').get('status')!='success':
        raise RuntimeError('Complete initialization or resume the failed run before publishing')
    from .site import build
    from .deployment import export
    build(root,config)  # Use the current frontend, never an old packaged snapshot.
    return dict(ready=True,update=result,export=export(root,output))
