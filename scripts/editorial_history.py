"""Durable history on a dedicated GitHub branch; no races with market SQLite commits."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BRANCH = 'cs2-skin-stories-history'
PATH = Path('data/editorial-history.json')


def api(route, method='GET', body=None):
    request = Request('https://api.github.com/repos/' + os.environ['GITHUB_REPOSITORY'] + route,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                               'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'},
                      method=method)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def get_file():
    try:
        return api('/contents/data/editorial-history.json?ref=' + BRANCH)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        # Distinguish a first run from a missing/deleted file on an existing branch.
        try:
            api('/git/ref/heads/' + BRANCH)
        except HTTPError as ref_exc:
            if ref_exc.code == 404:
                return None
            raise
        raise RuntimeError('History branch exists but its history file is missing; refusing to reset it') from exc


def main():
    action = sys.argv[1]
    if action == 'restore':
        remote = get_file()
        PATH.parent.mkdir(parents=True, exist_ok=True)
        if remote:
            data = base64.b64decode(remote['content'])
            if not isinstance(json.loads(data), list):
                raise ValueError('Remote history must be an array')
            PATH.write_bytes(data)
        else:
            PATH.write_text('[]\n')
        return
    if action != 'save':
        raise ValueError('Use restore or save')
    if not PATH.exists():
        return
    data = PATH.read_bytes()
    history = json.loads(data)
    if not history:
        return
    remote = get_file()
    if not remote:
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        base = api('/git/commits/' + sha)
        tree = api('/git/trees', 'POST', {'base_tree': base['tree']['sha'], 'tree': [
            {'path': 'data/editorial-history.json', 'mode': '100644', 'type': 'blob',
             'content': data.decode()}]})
        commit = api('/git/commits', 'POST', {'message': 'chore: initialize skin story history',
                     'tree': tree['sha'], 'parents': [sha]})
        api('/git/refs', 'POST', {'ref': 'refs/heads/' + BRANCH, 'sha': commit['sha']})
        return
    elif base64.b64decode(remote['content']) == data:
        return
    body = {'message': 'chore: record skin story history', 'branch': BRANCH,
            'content': base64.b64encode(data).decode()}
    if remote:
        body['sha'] = remote['sha']
    api('/contents/data/editorial-history.json', 'PUT', body)


if __name__ == '__main__':
    main()
