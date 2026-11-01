import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from core import activity_log


class ActivityLogTests(unittest.TestCase):
    def test_clear_removes_memory_and_disk_without_resetting_ids(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity_log, '_path', Path(tmp) / 'log.json'), patch.object(activity_log, '_entries', deque(maxlen=500)), patch.object(activity_log, '_sequence', 0):
            activity_log.record('first')
            first_id = activity_log.snapshot()[0]['id']
            activity_log.clear()
            self.assertEqual(activity_log.snapshot(), [])
            self.assertEqual(json.loads(activity_log._path.read_text(encoding='utf-8')), [])
            activity_log.record('next')
            self.assertGreater(activity_log.snapshot()[0]['id'], first_id)
