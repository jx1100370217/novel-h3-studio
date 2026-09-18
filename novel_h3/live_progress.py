"""Read-only ComfyUI event listener, scoped to the current take and prompt."""
from contextlib import closing
import json
import threading
import time
from urllib.parse import urlencode

import websocket

from .project import read


class LiveProgress:
    def __init__(self, root):
        self.root = root
        self.lock = threading.Lock()
        self.current = {}
        threading.Thread(target=self.run, daemon=True, name='comfy-progress').start()

    def get(self, prompt_id):
        with self.lock:
            return dict(self.current) if prompt_id and self.current.get('prompt_id') == prompt_id else {}

    def event(self, message, prompt_id, nodes):
        data = message.get('data', {})
        # Reconnect executing events omit prompt_id; never guess their identity.
        if data.get('prompt_id') != prompt_id:
            return
        kind = message.get('type')
        node = str(data.get('node'))
        class_type = nodes.get(node, {}).get('class_type', '')
        update = None
        if kind == 'progress' and class_type == 'SamplerCustomAdvanced':
            value, total = data.get('value', 0), data.get('max', 0)
            if total > 0 and 0 <= value <= total:
                update = {'steps': value, 'steps_total': total, 'stage': '采样'}
        elif kind == 'executing':
            if class_type == 'SamplerCustomAdvanced':
                stage = '采样初始化'
            elif class_type == 'MiniMaxH3MotionContextSaveLatent':
                stage = '保存采样结果'
            elif 'Decode' in class_type:
                stage = '解码视频与音频'
            elif class_type in ('CreateVideo', 'SaveVideo', 'SaveAudio', 'MiniMaxH3MotionContextTrim'):
                stage = '封装视频'
            elif data.get('node') is None:
                stage = '生成完成，等待核对'
            elif 'Loader' in class_type or class_type == 'ApplyVDNH3':
                stage = '准备模型'
            else:
                stage = '准备采样'
            update = {'steps': None, 'stage': stage}
        if update is not None:
            with self.lock:
                self.current = {**update, 'prompt_id': prompt_id, 'event_at': time.time()}

    def active(self):
        takes = read(self.root / 'state.json').get('takes', {}).values()
        return max((t for t in takes if not t.get('retired') and t.get('status') == 'submitted'
                    and t.get('prompt_id')), key=lambda t: t['created_at'], default=None)

    def run(self):
        while True:
            try:
                take = self.active()
                if not take:
                    time.sleep(1)
                    continue
                prompt_id = take['prompt_id']
                nodes = read(self.root / 'renders' / take['id'] / 'prompt.json')
                url = read(self.root / 'config.json')['comfy_url'].rstrip('/')
                url = url.replace('http://', 'ws://', 1).replace('https://', 'wss://', 1)
                # The runner reserves this client ID but opens no websocket.
                with closing(websocket.create_connection(url + '/ws?' + urlencode({'clientId': take['id']}), timeout=2)) as ws:
                    with self.lock:
                        self.current = {'prompt_id': prompt_id, 'steps': None,
                                        'stage': '已连接，等待实时进度'}
                    while True:
                        active = self.active()
                        if not active or active['prompt_id'] != prompt_id:
                            break
                        try:
                            raw = ws.recv()
                        except websocket.WebSocketTimeoutException:
                            continue
                        if not raw:
                            break
                        if isinstance(raw, str):
                            self.event(json.loads(raw), prompt_id, nodes)
            except (OSError, ValueError, KeyError, websocket.WebSocketException):
                time.sleep(2)


_listener = None
_listener_lock = threading.Lock()


def listener(root):
    global _listener
    with _listener_lock:
        if _listener is None:
            _listener = LiveProgress(root)
        return _listener
