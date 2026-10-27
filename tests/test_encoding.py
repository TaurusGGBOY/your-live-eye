"""Chinese progress must remain valid JSON on Windows redirected terminals."""
import contextlib
import io
import json
import unittest
from your_live_eye.util import log


class EncodingTests(unittest.TestCase):
    def test_progress_survives_a_non_unicode_terminal(self):
        buffer = io.BytesIO()
        output = io.TextIOWrapper(buffer, encoding='cp1252', errors='strict')
        with contextlib.redirect_stdout(output):
            log('channel_resolved', name='测试主播 🧋')
        output.flush()
        value = json.loads(buffer.getvalue().decode('cp1252'))
        self.assertEqual(value['name'], '测试主播 🧋')
        self.assertEqual(value['event'], 'channel_resolved')
