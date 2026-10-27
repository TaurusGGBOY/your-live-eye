"""Serve only generated static files; private state and raw archives are never routes."""
import functools
import gzip
import http.server
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote,urlsplit
import requests
from .util import now,read,save

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,root,**kwargs):
        self.root=Path(root)
        super().__init__(*args,directory=str(root),**kwargs)

    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        super().end_headers()

    def send_head(self):
        route=unquote(urlsplit(self.path).path)
        if route=='/':route='/index.html'
        if route not in ('/index.html','/app.js','/style.css','/favicon.svg','/data.json','/report.json') and not re.fullmatch(r'/(?:days|insights)/\d{4}-\d{2}-\d{2}\.json',route):
            self.send_error(404);return None
        site=Path(read(self.root/'current.json')['directory'])
        path=site/route.lstrip('/')
        if not path.is_file():self.send_error(404);return None
        compressed='gzip' in self.headers.get('Accept-Encoding','') and Path(str(path)+'.gz').is_file()
        source=Path(str(path)+'.gz') if compressed else path
        stream=source.open('rb')
        content_type=self.guess_type(str(path))
        if content_type.startswith('text/') or content_type in ('application/json','application/javascript'):
            content_type+='; charset=utf-8'
        self.send_response(200);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(os.fstat(stream.fileno()).st_size))
        self.send_header('Cache-Control','no-cache');self.send_header('Vary','Accept-Encoding')
        if compressed:self.send_header('Content-Encoding','gzip')
        self.end_headers();return stream

    def list_directory(self,path):self.send_error(404);return None

def serve(root,config):
    server=http.server.ThreadingHTTPServer((config['bind'],config['port']),functools.partial(Handler,root=root))
    server.serve_forever()

def lan_ip():
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1',80));return sock.getsockname()[0]
    except OSError:return socket.gethostbyname(socket.gethostname())

def service_command(config_path,action,prepare=True):
    if sys.platform=='darwin':
        # launchd cannot start reliably from removable volumes. Install an independent,
        # ordinary Python runtime in Application Support; never depend on the checkout.
        runtime=Path.home()/'Library/Application Support/YourLiveEye/runtime'
        python=runtime/'venv/bin/python'
        if prepare and not python.exists():
            subprocess.run([sys.executable,'-m','venv',str(runtime/'venv')],check=True,capture_output=True)
            subprocess.run([str(python),'-m','pip','install','requests>=2.31,<3','msgpack>=1,<2','tzdata>=2024.1'],check=True,capture_output=True)
        destination=runtime/'app/your_live_eye'
        source=Path(__file__).parent.resolve()
        if prepare and source!=destination.resolve():
            stage=runtime/'app/your_live_eye-next'
            if stage.exists():shutil.rmtree(stage)
            shutil.copytree(source,stage,copy_function=shutil.copyfile,ignore=shutil.ignore_patterns('._*','__pycache__'))
            previous=runtime/'app/your_live_eye-previous'
            if previous.exists():shutil.rmtree(previous)
            if destination.exists():destination.rename(previous)
            stage.rename(destination)
        return [str(python),'-m','your_live_eye',action,'--config',str(Path(config_path).resolve())]
    return [sys.executable,'-m','your_live_eye',action,'--config',str(Path(config_path).resolve())]

def launchd_install(label,args,root,interval=None):
    root=Path(root);logs=root/'logs';logs.mkdir(exist_ok=True)
    path=Path.home()/'Library/LaunchAgents'/f'{label}.plist';path.parent.mkdir(parents=True,exist_ok=True)
    domain=f'gui/{os.getuid()}';service=domain+'/'+label
    config={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(root),'RunAtLoad':True,
            'EnvironmentVariables':{'PATH':str(Path.home()/'.local/bin')+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
                                    'LANG':'en_US.UTF-8','PYTHONUNBUFFERED':'1',
                                    'PYTHONPATH':str(Path.home()/'Library/Application Support/YourLiveEye/runtime/app')},
            'StandardOutPath':str(logs/(label+'.out.log')),'StandardErrorPath':str(logs/(label+'.err.log'))}
    if interval:config['StartInterval']=interval
    else:config['KeepAlive']=True
    if path.exists():
        previous=plistlib.loads(path.read_bytes())
        if previous.get('ProgramArguments')!=args:raise RuntimeError('Service name already belongs to another configuration: '+str(path))
        status=subprocess.run(['launchctl','print',service],capture_output=True)
        if status.returncode==0:return {'executor':'launchd','label':label,'path':str(path)}
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True,capture_output=True)
    return {'executor':'launchd','label':label,'path':str(path)}

def systemd_install(label,args,root,timer=False):
    root=Path(root);folder=Path.home()/'.config/systemd/user';folder.mkdir(parents=True,exist_ok=True)
    def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    cmd=' '.join(quote(a) for a in args)
    service=folder/(label+'.service')
    content=f'[Unit]\nDescription=YourLiveEye {label}\nAfter=network-online.target\n[Service]\nType={"oneshot" if timer else "simple"}\nExecStart={cmd}\nWorkingDirectory={quote(root)}\n'
    if not timer:content+='Restart=on-failure\n[Install]\nWantedBy=default.target\n'
    if service.exists() and service.read_text()!=content:raise RuntimeError('Service name already belongs to another configuration')
    service.write_text(content)
    unit=label+'.service'
    if timer:
        unit=label+'.timer'
        (folder/unit).write_text(f'[Unit]\nDescription=YourLiveEye Shanghai 04:00 catch-up\n[Timer]\nOnBootSec=2m\nOnUnitActiveSec=15m\nPersistent=true\nUnit={label}.service\n[Install]\nWantedBy=timers.target\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now',unit],check=True)
    return dict(executor='systemd',label=label,path=str(service),unit=unit)

def windows_install(label,args,root,timer=False):
    # Task Scheduler launches a fixed command; shell text is never constructed from nickname input.
    command=subprocess.list2cmdline(args)
    check=subprocess.run(['schtasks','/Query','/TN',label,'/XML'],capture_output=True,text=True)
    if check.returncode==0:
        raise RuntimeError('Task already exists; use existing task or unschedule before replacing: '+label)
    cadence=['/SC','MINUTE','/MO','15'] if timer else ['/SC','ONLOGON']
    subprocess.run(['schtasks','/Create','/TN',label,'/TR',command,*cadence,'/F'],check=True)
    if not timer:subprocess.run(['schtasks','/Run','/TN',label],check=True)
    return dict(executor='schtasks',label=label)

def deploy(root,config):
    root=Path(root);port=config['port'];probe=f'http://127.0.0.1:{port}'
    label=f'org.yourliveeye.{config["channel"]["uid"]}.web-{port}'
    # An occupied port must never be mistaken for this project's successful deployment.
    try:
        existing=requests.get(probe+'/data.json',timeout=2)
    except requests.RequestException:existing=None
    if existing is not None:
        saved=read(root/'access.json') if (root/'access.json').exists() else None
        if not saved or existing.status_code!=200 or existing.json().get('channel',{}).get('uid')!=config['channel']['uid']:
            raise RuntimeError(f'Port {port} is already occupied; choose another --port')
        return saved
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe_socket:
        # Match HTTPServer's reuse policy: a stopped service's TIME_WAIT sockets
        # must not be mistaken for another listener during an upgrade.
        probe_socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:probe_socket.bind((config['bind'],port))
        except OSError:raise RuntimeError(f'Port {port} is occupied on a network interface; choose another --port') from None
    args=service_command(root/'config.json','serve')
    if sys.platform=='darwin':service=launchd_install(label,args,root)
    elif sys.platform.startswith('linux') and shutil.which('systemctl'):
        service=systemd_install(label,args,root)
    elif os.name=='nt':service=windows_install(label,args,root)
    else:
        logs=root/'logs';logs.mkdir(exist_ok=True)
        with (logs/'server.log').open('a') as out:
            proc=subprocess.Popen(args,stdout=out,stderr=out,start_new_session=True,cwd=root)
        service=dict(executor='process',pid=proc.pid,label=label)
    access=dict(service,uid=config['channel']['uid'],port=port,bind=config['bind'],
                url=f'http://{lan_ip() if config["bind"]=="0.0.0.0" else config["bind"]}:{port}/',
                local_url=probe+'/',installed_at=now())
    save(root/'access.json',access)
    for attempt in range(30):
        try:
            verify(root,config,access);return access
        except requests.RequestException:time.sleep(.3)
    raise RuntimeError('Web service did not start; inspect private logs')

def verify(root,config,access=None):
    root=Path(root);access=access or read(root/'access.json')
    site=Path(read(root/'current.json')['directory']);expected=read(site/'data.json')
    response=requests.get(access['local_url']+'data.json',timeout=5);response.raise_for_status();actual=response.json()
    if (actual['channel']['uid'],actual['generated_at'],actual['totals'])!=(expected['channel']['uid'],expected['generated_at'],expected['totals']):
        raise RuntimeError('Served snapshot differs from the newly built one')
    for route in ('','days/'+expected['default_date']+'.json','insights/'+expected['default_date']+'.json'):
        r=requests.get(access['local_url']+route,timeout=5);r.raise_for_status()
    return dict(verified_at=now(),url=access['url'],events=actual['totals']['all']['total'])

def remove_service(service):
    if service['executor']=='launchd':
        subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{service["label"]}'],check=False,capture_output=True)
        Path(service['path']).unlink(missing_ok=True)
    elif service['executor']=='systemd':
        subprocess.run(['systemctl','--user','disable','--now',service['unit']],check=True)
        Path(service['path']).unlink(missing_ok=True)
        if service['unit'].endswith('.timer'):Path(service['path']).with_suffix('.timer').unlink(missing_ok=True)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    elif service['executor']=='schtasks':
        subprocess.run(['schtasks','/End','/TN',service['label']],check=False,capture_output=True)
        subprocess.run(['schtasks','/Delete','/TN',service['label'],'/F'],check=True)
    else:
        result=subprocess.run(['ps','-p',str(service['pid']),'-o','command='],capture_output=True,text=True)
        if 'your_live_eye serve --config' in result.stdout:os.kill(service['pid'],signal.SIGTERM)

def stop(root):
    path=Path(root)/'access.json'
    if not path.exists():return {'stopped':False,'reason':'no registered service'}
    remove_service(read(path));path.unlink();return {'stopped':True}

def export(root,output):
    root=Path(root);output=Path(output).resolve()
    if output.exists():raise FileExistsError('Export destination exists: '+str(output))
    site=Path(read(root/'current.json')['directory'])
    from .site import validate
    validate(site);shutil.copytree(site,output,ignore=shutil.ignore_patterns('._*','.DS_Store'))
    return dict(output=str(output),files=sum(1 for p in output.rglob('*') if p.is_file()),contains_raw_archive=False)
