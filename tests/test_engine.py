"""Exercise the worker protocol with a real subprocess and a lightweight stand-in for CUDA."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import serveur_inkforge as studio


def fake_load():
    def reconstruct(folder,quality):
        if folder.name=='error':raise RuntimeError('simulated OOM')
        (folder/'model.glb').write_bytes(quality.encode())
        return 123
    return reconstruct


class EngineTests(unittest.TestCase):
    def test_warm_lifetime_quality_cache_and_failure(self):
        worker=studio.WarmEngine(idle=.5)
        self.addCleanup(worker.stop)
        popen=subprocess.Popen
        def start(_,**kwargs):
            return popen([sys.executable,__file__,'child'],**kwargs)
        with tempfile.TemporaryDirectory() as tmp, patch.object(studio.subprocess,'Popen',start), patch.object(studio,'warm_engine',worker):
            root=Path(tmp)
            with patch.object(studio,'WORK',root),patch.object(studio,'LOCAL_3D',root):
                (root/'ready-v1').touch()
                req={'image':'data:image/png;base64,YWJj'}
                preview=studio.build_character_model(dict(req,quality='preview'))
                final=studio.build_character_model(req)
                self.assertTrue(preview['cold'])
                self.assertFalse(final['cold'])
                self.assertNotEqual(preview['id'],final['id'])
                self.assertTrue(studio.build_character_model(req)['cached'])
                for result,quality in [(preview,'preview'),(final,'final')]:
                    self.assertEqual((root/'models'/result['id']/'model.glb').read_text(),quality)
                worker.stop()
                with ThreadPoolExecutor(2) as pool:
                    jobs=list(pool.map(lambda _:worker.run(root,'preview'),range(2)))
                self.assertEqual(sum(j['cold'] for j in jobs),1)
                process=worker.process
                process.wait(timeout=8)
                self.assertTrue(worker.run(root,'final')['cold'])
                with self.assertRaises(studio.ClientFailure):worker.run(root/'error','final')
                self.assertIsNone(worker.process)
                self.assertTrue(worker.run(root,'final')['cold'])
                worker.stop()
                self.assertTrue(studio.build_character_model(req)['cached'])
                self.assertIsNone(worker.process)


if __name__=='__main__':
    if sys.argv[1:]==['child']:studio.engine_loop(sys.stdin,sys.stdout,fake_load)
    else:unittest.main()
