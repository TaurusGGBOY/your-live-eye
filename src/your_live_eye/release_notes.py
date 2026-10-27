"""Build the visible version and release history from one maintained record."""
import html
import json
import re
from pathlib import Path

RELEASES = Path(__file__).with_name('releases.json')
VERSION = '{{APP_VERSION}}'
START = '<!-- release-notes:start -->'
END = '<!-- release-notes:end -->'


def render(source):
    # Data-only refreshes retain the release of their already assembled frontend.
    if VERSION not in source:
        return source
    releases = json.loads(RELEASES.read_text(encoding='utf-8'))
    if not releases or any(not entry['changes'] or
                           any(not change.strip() for change in entry['changes'])
                           for entry in releases):
        raise ValueError('每个版本必须记录具体改动：请补充 src/your_live_eye/releases.json 的 changes')
    entries = []
    for index, entry in enumerate(releases):
        version = html.escape(entry['version'], quote=True)
        date = html.escape(entry['date'], quote=True)
        title = html.escape(entry['title'])
        changes = ''.join(f'<li>{html.escape(change)}</li>' for change in entry['changes'])
        current = '<span class="release-current">当前版本</span>' if index == 0 else ''
        entries.append(f'<article class="release-entry" aria-labelledby="release-{version}">'
                       f'<div class="release-meta"><span class="release-version">v{version}</span>'
                       f'{current}<time datetime="{date}">{date}</time></div>'
                       f'<h3 id="release-{version}">{title}</h3><ul>{changes}</ul></article>')
    source = source.replace(VERSION, html.escape(releases[0]['version'], quote=True))
    block = START + '\n' + '\n'.join(entries) + '\n' + END
    return re.sub(re.escape(START) + '.*?' + re.escape(END), lambda _: block, source, flags=re.S)
