import argparse
import json
import sys
from pathlib import Path
from .source import Source,BASE
from .util import log,read,save,default_state

def main():
    parser=argparse.ArgumentParser(description='你的眼 YourLiveEye · resolve, analyse, schedule and deploy a Bilibili live room')
    sub=parser.add_subparsers(dest='command',required=True)
    resolve=sub.add_parser('resolve');resolve.add_argument('target');resolve.add_argument('--source-base',default=BASE)
    run=sub.add_parser('run');run.add_argument('target',help='UP UID, exact nickname, profile URL or live-room URL')
    run.add_argument('--state',type=Path,default=default_state())
    scope=run.add_mutually_exclusive_group()
    scope.add_argument('--date',default='all',help='all (default), latest, or YYYY-MM-DD')
    scope.add_argument('--demo',dest='date',action='store_const',const='latest',help='Explicit lightweight demo: latest finished session only')
    run.add_argument('--fallback-latest',action='store_true')
    run.add_argument('--configure-only',action='store_true',help='Save configuration without downloading, classifying or publishing')
    run.add_argument('--update-at',default='04:00',help='Daily local HH:MM, default 04:00')
    run.add_argument('--timezone',default='Asia/Shanghai',help='IANA timezone for the daily job (chart dates remain Beijing time)')
    run.add_argument('--source-base',default=BASE)
    run.add_argument('--provider',choices=['codex','openai'],default='codex')
    run.add_argument('--model',default='gpt-6-luna')
    run.add_argument('--reasoning',default='high');run.add_argument('--tier',default='fast')
    run.add_argument('--batch-size',type=int,default=8192);run.add_argument('--batch-bytes',type=int,default=200000)
    run.add_argument('--review-batch-size',type=int,default=32);run.add_argument('--concurrency',type=int,default=2)
    run.add_argument('--timeout',type=int,default=900);run.add_argument('--max-attempts',type=int,default=3)
    run.add_argument('--deploy',action='store_true');run.add_argument('--bind',default='0.0.0.0');run.add_argument('--port',type=int,default=18770)
    run.add_argument('--schedule',action='store_true',help='Install daily catch-up at --update-at / --timezone')
    for name in ('resume','status','rebuild','schedule','unschedule','deploy','stop','verify','export','cloudflare-build'):
        p=sub.add_parser(name);p.add_argument('--config',type=Path,required=True)
        if name=='resume':p.add_argument('--retry-failed',action='store_true')
        if name=='schedule':p.add_argument('--print-only',action='store_true')
        if name=='export':p.add_argument('--output',type=Path,required=True)
        if name=='cloudflare-build':
            p.add_argument('--output',type=Path,required=True)
            p.add_argument('--mode',choices=['publish','update','scheduled'],default='publish')
    scheduled=sub.add_parser('scheduled');scheduled.add_argument('--config',type=Path,required=True)
    serve=sub.add_parser('serve');serve.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='resolve':
            channel,catalogue=Source(args.source_base).resolve(args.target)
            print(json.dumps(channel,ensure_ascii=False,indent=2));return
        if args.command=='run':
            from .schedule import schedule_options
            schedule_options({'update_at':args.update_at,'timezone':args.timezone})
            if args.configure_only and args.schedule:
                raise ValueError('--configure-only does not install a timer; use schedule --config after reviewing the saved configuration')
            if not 1<=args.concurrency<=16 or not 1<=args.batch_size<=8192 or args.batch_bytes<1024 or args.review_batch_size<1:
                raise ValueError('Concurrency 1..16, batch size 1..8192, review batch positive, batch bytes >=1024 required')
            channel,catalogue=Source(args.source_base).resolve(args.target)
            root=args.state.resolve()/str(channel['uid']);config_path=root/'config.json'
            settings={k:getattr(args,k) for k in ('provider','model','reasoning','tier','batch_size','batch_bytes','review_batch_size','concurrency','timeout','max_attempts')}
            config=dict(channel=channel,date=args.date,fallback_latest=args.fallback_latest,source_base=args.source_base,
                        model=settings,deploy=args.deploy,bind=args.bind,port=args.port,timezone=args.timezone,update_at=args.update_at,schema=1)
            if config_path.exists():
                previous=read(config_path)
                if dict(previous,update_at=previous.get('update_at','04:00'))!=config:
                    raise ValueError('Existing configuration differs. Use `resume --config '+str(config_path)+'` or a separate --state directory.')
            else:save(config_path,config)
            log('channel_resolved',config=str(config_path),**channel)
            if args.configure_only:return
            from .pipeline import run as run_pipeline
            try:
                run_pipeline(config_path,initial=True)
            finally:
                # Keep the requested daily recovery available even if initialization failed.
                if args.schedule:
                    from .schedule import install
                    print(json.dumps(install(config_path),ensure_ascii=False,indent=2))
            return
        config_path=args.config.resolve();config=read(config_path);root=config_path.parent
        if args.command=='resume':
            from .pipeline import run as run_pipeline
            result=run_pipeline(config_path,retry_failed=args.retry_failed)
        elif args.command=='status':
            from .store import summary
            result={'classification':summary(root),'run':read(root/'last-run.json') if (root/'last-run.json').exists() else None}
        elif args.command=='rebuild':
            from .site import build
            result={'site':str(build(root,config))}
        elif args.command=='cloudflare-build':
            from .cloudflare import prepare
            result=prepare(config_path,args.output,args.mode)
        elif args.command in ('schedule','unschedule','scheduled'):
            from .schedule import install,uninstall,tick
            result=install(config_path,args.print_only) if args.command=='schedule' else uninstall(config_path) if args.command=='unschedule' else tick(config_path)
        elif args.command=='serve':
            from .deployment import serve
            serve(root,config);return
        else:
            from .deployment import deploy,stop,verify,export
            result=deploy(root,config) if args.command=='deploy' else stop(root) if args.command=='stop' else verify(root,config) if args.command=='verify' else export(root,args.output)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (Exception,KeyboardInterrupt) as error:
        log('error',error_type=type(error).__name__,message=str(error));sys.exit(1)
