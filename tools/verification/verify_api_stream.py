"""Offline check of concurrent SSE results, duplicate names and per-file errors."""
import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import UploadFile
from backend import api


class FakeTranslator:
    def __init__(self, **kwargs):
        pass


async def verify():
    release_slow = threading.Event()
    completion_order = []

    def process(translator, path, extension):
        content = Path(path).read_bytes()
        if content == b'failed':
            raise ValueError('fixture translation failure')
        if content == b'slow' and not release_slow.wait(5):
            raise TimeoutError('fast result did not arrive independently')
        return io.BytesIO(content + b' translated')

    async def run(content):
        upload = UploadFile(filename='same.xlsx', file=io.BytesIO(content))
        try:
            response = await api.translate_document_stream(upload, 'English', 'google-translate', None)
            events = []
            async for frame in response.body_iterator:
                if frame.startswith('data: '):
                    event = json.loads(frame[6:])
                    events.append(event)
                    if event['type'] == 'complete':
                        completion_order.append(content)
                        if content == b'fast':
                            release_slow.set()
            return events[-1]
        finally:
            await upload.close()

    with tempfile.TemporaryDirectory() as directory, \
            patch.object(api, 'OUTPUT_DIR', directory), \
            patch.object(api, '_get_translator_modules', return_value=(None, None, FakeTranslator, None, None)), \
            patch.object(api, '_process_file_with_translator', side_effect=process), \
            patch.object(api, 'get_cloud_console_links', return_value={}), \
            patch.object(api, 'save_ephemeral_output_file', return_value=(False, None)), \
            patch.object(api, 'record_execution_run'):
        slow, fast, failed = await asyncio.gather(run(b'slow'), run(b'fast'), run(b'failed'))
        assert completion_order == [b'fast', b'slow'], completion_order
        assert slow['filename'] != fast['filename']
        for event, content in [(slow, b'slow'), (fast, b'fast')]:
            assert event['type'] == 'complete'
            assert base64.b64decode(event['file_b64']) == content + b' translated'
            assert Path(directory, event['filename']).read_bytes() == content + b' translated'
        assert failed['type'] == 'error'
        assert failed['message'] == 'fixture translation failure'
        assert not list(Path(directory).glob('temp_*'))
    print('Concurrent SSE completion, filename isolation, failure isolation and input cleanup passed')


if __name__ == '__main__':
    asyncio.run(verify())
