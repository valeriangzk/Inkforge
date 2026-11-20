"""Admission at the relay, including requests from independent browser tabs."""
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serveur_inkforge as studio


class AdmissionTest(unittest.TestCase):
    def test_ticket_key_and_shared_quota(self):
        finish = threading.Event()
        refused = studio.ClientFailure('Quota de test', 502)
        refused.provider_status = 429
        refused.retry_after = 120

        def simulate(payload, key):
            finish.wait(5)
            raise refused

        first = {'requestId': str(uuid.uuid4())}
        second = {'requestId': str(uuid.uuid4())}
        with patch.object(studio, 'send_generate', side_effect=simulate) as provider:
            ticket = studio.generation_ticket(first, 'test-key')
            self.assertEqual(studio.generation_ticket(first, 'test-key'), ticket)
            self.assertIn('deferred', studio.generation_ticket(second, 'test-key'))
            with patch.object(studio, 'IMAGE_RPM', 1):
                self.assertIn('deferred', studio.generation_ticket(second, 'another-test-key'))
            finish.set()
            for _ in range(100):
                with studio.WORK_LOCK:
                    if not studio.generation_jobs[ticket['ticket']].get('pending'):
                        break
                time.sleep(0.01)
            result = studio.generation_jobs[ticket['ticket']]
            self.assertEqual(result['provider_status'], 429)
            self.assertEqual(result['retry_after'], 120)
            self.assertGreaterEqual(studio.generation_ticket(second, 'another-test-key')['deferred'], 119)
            self.assertEqual(provider.call_count, 1)
            self.assertFalse(studio.generation_keys)


if __name__ == '__main__':
    unittest.main()
