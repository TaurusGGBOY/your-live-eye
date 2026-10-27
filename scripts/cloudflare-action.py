"""GitHub entry point. Values are configuration, not shell snippets."""
import os
import re
import tempfile
import subprocess
import sys
from pathlib import Path
from your_live_eye.cloudflare import prepare
from your_live_eye.util import read
from your_live_eye import checkpoint

def hosted_config(temp):
    from your_live_eye.cloud_state import CloudState
    uid=os.environ['YOUR_LIVE_EYE_UID'];cloud=CloudState(uid)
    root=temp/'your-live-eye-state'/str(int(uid))
    restored=cloud.restore(root)
    config=root/'config.json'
    if not restored:
        if not os.environ.get('YOUR_LIVE_EYE_API_KEY'):raise ValueError('Hosted initialization needs a model API Secret')
        model=os.environ.get('YOUR_LIVE_EYE_MODEL')
        if not model:raise ValueError('Choose an available API model in YOUR_LIVE_EYE_MODEL')
        subprocess.run([sys.executable,'-m','your_live_eye','run',uid,'--state',str(root.parent),
            '--configure-only','--provider','openai','--model',model,'--tier','default',
            '--date',os.environ.get('YOUR_LIVE_EYE_SCOPE') or 'all',
            '--update-at',os.environ.get('YOUR_LIVE_EYE_UPDATE_AT') or '04:00',
            '--timezone',os.environ.get('YOUR_LIVE_EYE_TIMEZONE') or 'Asia/Shanghai'],check=True)
    settings=read(config)
    if settings['model']['provider']!='openai' or settings.get('deploy'):
        raise ValueError('Hosted state requires API mode without a local web service')
    # Leave ample time below the six-hour hosted job limit for running requests
    # to finish and the final checkpoint to upload.
    checkpoint.configure(cloud.save,max_seconds=16200)
    return config,cloud

def main():
    project=os.environ['YOUR_LIVE_EYE_CF_PROJECT']
    branch=os.environ.get('YOUR_LIVE_EYE_CF_BRANCH','main')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,57}[a-z0-9]|[a-z0-9]',project):
        raise ValueError('Cloudflare project name must be lowercase letters, digits or hyphens')
    # These values become Wrangler arguments; prohibit whitespace and option injection.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',branch):
        raise ValueError('Cloudflare branch must be a plain branch name')
    temp=Path('/tmp/codextmp');temp.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='your-live-eye-pages-',dir=temp))/'site'
    cloud=None
    if os.environ.get('YOUR_LIVE_EYE_RUNNER')=='self-hosted':
        config=Path(os.environ['YOUR_LIVE_EYE_CONFIG']).expanduser()
        if not config.is_absolute() or not config.is_file():
            raise ValueError('Set YOUR_LIVE_EYE_CONFIG to an existing absolute config.json on the persistent runner')
    else:
        config,cloud=hosted_config(temp)
    try:
        result=prepare(config,folder,os.environ.get('YOUR_LIVE_EYE_ACTION_MODE','publish'))
    finally:
        checkpoint.configure()
        if cloud is not None:cloud.save(config.parent)
    with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as stream:
        stream.write('ready='+str(result['ready']).lower()+'\n')
        if result['ready']:stream.write('directory='+str(folder)+'\n')
    print('Static export ready for Cloudflare.' if result['ready'] else 'No completed update to publish: '+result['update']['status'])

if __name__=='__main__':main()
