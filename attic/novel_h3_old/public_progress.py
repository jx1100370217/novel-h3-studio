"""Public read-only projection. No workbench controls or arbitrary file access."""
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .server import Handler
from .progress import snapshot
from .project import read, inside


def public_snapshot(root):
    result = snapshot(root)
    result['pause_reason'] = '任务已暂停，请在本机查看具体错误' if result['paused'] else None
    state = read(root/'state.json')
    for item in result['recent']:
        path = item.pop('video', None)
        matching = [t for t in state['takes'].values() if path and t.get('video') == path
                    and t['status'] in ('rendered', 'approved')]
        item['video_url'] = '/video?id=' + matching[-1]['id'] if matching else None
    return result



class PublicHandler(Handler):
    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path == '/':
                return self.file(Path(__file__).with_name('public_progress.html'))
            if url.path == '/api/progress':
                return self.send_json(public_snapshot(self.root))
            if url.path == '/video':
                tid = parse_qs(url.query).get('id', [''])[0]
                take = read(self.root/'state.json')['takes'].get(tid)
                if take and take['status'] in ('rendered', 'approved') and take.get('video'):
                    path = inside(self.root, take['video'])
                    if path.suffix == '.mp4':
                        return self.file(path)
            self.send_error(404)
        except (ValueError, KeyError, OSError):
            self.send_json({'error': '进度暂不可用，请稍后重试'}, 503)

    def do_POST(self):
        self.send_error(405)


def serve(root, port=8766):
    server = ThreadingHTTPServer(('127.0.0.1', port), PublicHandler)
    server.project = root
    server.serve_forever()


if __name__ == '__main__':
    serve(Path(__file__).resolve().parents[1]/'projects/rendao-wuji')
