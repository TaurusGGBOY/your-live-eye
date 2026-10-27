"""Public Danmakus source adapter; no account, cookie, or token access."""
import datetime as dt
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import msgpack
import requests

from .live_window import live_interval
from .util import TZ, now, read, save, log

EVENTS = ['Message','Gift','Guard','SC','Enter','Title','Area','Pause_Stop',
          'Pause_Continue','Block','Warning','Record_Start','Record_Interrupt','Owner']
BASE = 'https://ukamnads.icu'

class SourceError(RuntimeError):
    pass

class Source:
    def __init__(self, base=BASE):
        self.base = base.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({'User-Agent':'YourLiveEye/0.1 (public archive analysis)'})

    def get(self, path, **kwargs):
        url = path if path.startswith('https://') else self.base + path
        for attempt in range(3):
            try:
                response = self.session.get(url, timeout=90, **kwargs)
                # Do not circumvent access controls or rate limits with other hosts.
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                status = getattr(error.response, 'status_code', None)
                if attempt == 2 or status in (400,401,403,404,429):
                    raise SourceError(f'Source unavailable ({status or type(error).__name__}): {url}') from None
                time.sleep(2 ** attempt)

    def api(self, path, **params):
        data = self.get(path, params=params).json()
        if data.get('code') != 200 or data.get('data') is None:
            raise SourceError('Archive returned no usable data: ' + path)
        return data['data']

    def catalogue(self, uid):
        data = self.api('/api/v2/channel', uId=int(uid))
        if int(data.get('channel',{}).get('uId',0)) != int(uid) or not isinstance(data.get('lives'),list):
            raise SourceError('Catalogue channel identity mismatch')
        return data

    def resolve(self, target):
        value = target.strip()
        uid = room = None
        if value.isdigit():
            uid = int(value)
        elif value.startswith(('https://','http://')):
            parsed = urlparse(value)
            host = (parsed.hostname or '').lower()
            if host == 'b23.tv':
                value = self.get(value).url
                parsed = urlparse(value); host = (parsed.hostname or '').lower()
            match = re.search(r'^/(\d+)(?:/|$)', parsed.path)
            if host in ('space.bilibili.com','m.bilibili.com'):
                match = re.search(r'(?:^/|/space/)(\d+)(?:/|$)',parsed.path)
                if match: uid = int(match.group(1))
            elif host == 'live.bilibili.com' and match:
                room = int(match.group(1))
            elif host in ('danmakus.com','www.danmakus.com'):
                match = re.search(r'^/channel/(\d+)', parsed.path)
                if match: uid = int(match.group(1))
            if uid is None and room is None:
                raise SourceError('Supported links: Bilibili profile/live room or Danmakus channel. Use UID for other links.')
        else:
            result = self.api('/api/v2/channel/filter', keyword=value)
            candidates = result.get('data',[])
            exact = [r for r in candidates if r.get('uName') == value]
            if len(exact) != 1:
                choices = [{'uid':r.get('uId'),'name':r.get('uName'),'room_id':r.get('roomId')} for r in candidates[:20]]
                raise SourceError('Nickname is absent or ambiguous; provide a UID. Candidates: '+json.dumps(choices,ensure_ascii=False))
            uid = int(exact[0]['uId'])
        if room is not None:
            result = self.get('https://api.live.bilibili.com/room/v1/Room/get_info',params={'room_id':room}).json()
            if result.get('code') != 0 or not result.get('data',{}).get('uid'):
                raise SourceError('Could not resolve room owner; supply the UP UID')
            uid = int(result['data']['uid'])
        data = self.catalogue(uid)
        return self.identity(data['channel']), data

    @staticmethod
    def identity(channel):
        return {'uid':int(channel['uId']), 'name':channel['uName'], 'room_id':int(channel['roomId']),
                'live_url':f"https://live.bilibili.com/{channel['roomId']}",
                'profile_url':f"https://space.bilibili.com/{channel['uId']}",
                'source_url':f"https://danmakus.com/channel/{channel['uId']}"}

    def acquire(self, live, channel, root, refresh=False):
        folder = Path(root)/'raw'/live['liveId']
        folder.mkdir(parents=True,exist_ok=True)
        path = folder/'response.msgpack'
        if not path.exists() or refresh:
            url = f"{self.base}/api/v3/lives/{live['liveId']}/full?include=extra&includeEnter=false"
            raw = self.get(url,headers={'Accept':'application/x-msgpack'}).content
            metadata, events = decode(live['liveId'],raw,channel)
            # Keep the prior successful response if the archive revises a session.
            if path.exists() and path.read_bytes() != raw:
                path.replace(folder/('response-'+str(time.time_ns())+'.msgpack'))
            path.write_bytes(raw)
            save(folder/'request.json',dict(url=url,fetched_at=now(),bytes=len(raw),rows=len(events)))
        else:
            metadata, events = decode(live['liveId'],path.read_bytes(),channel)
        if not events and live.get('danmakusCount',0)>0:
            raise SourceError('Archive claims messages but returned an empty payload')
        save(folder/'live.json',live)
        log('source_ready',live_id=live['liveId'],rows=len(events))
        return events

def decode(lid, raw, channel):
    """Generalized from Hinome's tested MessagePack delta-timestamp decoder."""
    data = msgpack.unpackb(raw,raw=False,strict_map_key=False)
    if int(data[0][0]) != channel['uid'] or int(data[0][2]) != channel['room_id']:
        raise SourceError('Downloaded session belongs to a different channel')
    timestamp, actors, emoji, rows = data[2]
    events=[]
    for index, (delta,typ,actor,upload,kind,payload) in enumerate(rows):
        timestamp += delta or 0
        events.append({'live_id':lid,'source_row':index,'timestamp_ms':timestamp,
                       'event_type':EVENTS[typ] if 0<=typ<len(EVENTS) else f'Unknown_{typ}',
                       'payload_kind':kind,'payload':payload})
    return data, events

def select_sessions(catalogue, date='all', fallback_latest=False, clock=None):
    clock = clock or dt.datetime.now(TZ)
    finished = sorted((x for x in catalogue['lives'] if x.get('isFinish') and live_interval(x)
                       and x['stopDate'] <= clock.timestamp()*1000),key=lambda x:x['startDate'],reverse=True)
    if not finished:
        raise SourceError('No finished session with verified live boundaries in this archive')
    if date == 'all':
        return finished, {'selection':'all_finished','requested_date':'all',
                          'eligible_sessions':len(finished),
                          'deferred_sessions':len(catalogue['lives'])-len(finished)}
    if date == 'latest':
        return finished[:1], {'selection':'latest_finished','requested_date':'latest'}
    day = dt.date.fromisoformat(date)
    if day > clock.date(): raise SourceError('Future date is not eligible')
    lo = int(dt.datetime.combine(day,dt.time(),TZ).timestamp()*1000); hi=lo+86400000
    selected = [x for x in finished if x['startDate']<hi and x['stopDate']>=lo]
    if not selected:
        if not fallback_latest: raise SourceError('No archived finished session overlaps this date; use --fallback-latest explicitly')
        return finished[:1], {'selection':'latest_finished_fallback','requested_date':date,
                              'note':'Requested date not present in archive; not evidence of no live stream.'}
    return selected, {'selection':'date_overlap','requested_date':date}
