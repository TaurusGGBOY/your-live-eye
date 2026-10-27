"""Embed the latest day's small viewer payload so history never blocks first paint."""
import argparse
import gzip
import json
import re
from pathlib import Path
from .release_notes import render as render_release_notes

START = '<!-- first-screen:start -->'
END = '<!-- first-screen:end -->'
META = ('schema_version', 'as_of', 'generated_at', 'min_date', 'default_date',
        'first_observed', 'channel', 'classification_status', 'topics', 'daily_insights', 'insights_generated_at')


def embed(site):
    site = Path(site)
    data = json.loads((site / 'data.json').read_text())
    day = data['default_date']
    payload = ''
    if day in data['calendar'] and (site / 'days' / f'{day}.json').is_file():
        index = {key: data[key] for key in META if key in data}
        index['source'] = {'channel_url': data['source']['channel_url']}
        index['calendar'] = {day: data['calendar'][day]}
        index['observed_dates'] = [d for d, row in data['calendar'].items() if row['observed']]
        bootstrap = {'snapshot': index, 'day': json.loads((site / 'days' / f'{day}.json').read_text())}
        insight = site / 'insights' / f'{day}.json'
        if data.get('daily_insights') and insight.is_file():
            bootstrap['insights'] = json.loads(insight.read_text())
        payload = json.dumps(bootstrap, ensure_ascii=False, separators=(',', ':'))
        # Anonymous source text can contain HTML; keep it inside the inert JSON block.
        for char in ('<', '>', '&', '\u2028', '\u2029'):
            payload = payload.replace(char, f'\\u{ord(char):04x}')
        payload = f'<script id="first-screen" type="application/json">{payload}</script>'
    html = render_release_notes((site / 'index.html').read_text())
    block = START + payload + END
    html = re.sub(re.escape(START) + '.*?' + re.escape(END), lambda _: block, html, flags=re.S)
    target = site / 'index.html'
    temp = target.with_suffix('.html.tmp')
    temp.write_text(html)
    temp.replace(target)
    compressed = site / 'index.html.gz'
    temp = compressed.with_suffix('.gz.tmp')
    temp.write_bytes(gzip.compress(html.encode(), compresslevel=9, mtime=0))
    temp.replace(compressed)
