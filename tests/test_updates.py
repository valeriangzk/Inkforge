import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FILES=('serveur_inkforge.py','INKFORGE.html','version.json','LISEZ_MOI.txt','LANCER_INKFORGE.cmd')


def load(root):
    spec=importlib.util.spec_from_file_location('isolated_studio',root/'serveur_inkforge.py')
    app=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    app.LOCAL_3D=root/'runtime'
    return app


def package(version):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.writestr(name,json.dumps({'version':version}) if name=='version.json' else (ROOT/name).read_bytes())
    return output.getvalue()


class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve()
        for name in FILES:shutil.copy2(ROOT/name,self.base/name)
        self.app=load(self.base)

    def populate(self,name):
        a=self.app
        media=a.store_media(b'fixture-pixels-'+name.encode(),'image/png')
        model=a.WORK/'models'/'abcdef'/'model.glb'
        model.parent.mkdir(parents=True,exist_ok=True)
        model.write_bytes(b'3D mesh '+name.encode())
        p={'id':name,'title':name,'characters':[{'name':name,'references':[media]}],
           'places':[{'img':media}], 'pages':[[{'img':media}]]}
        data=dict(a.EMPTY_WORK,revision=a.read_workspace()['revision'],projects={name:p},active=name,histories={name:[{'project':p}]})
        a.save_workspace(data)
        return (a.WORK/'state.json').read_bytes()

    def upgrade(self,version):
        a=self.app
        self.assertEqual(a.install_zip(package(version),version),version)
        with self.assertRaises(a.ClientFailure):a.require_live()
        self.app=load(self.base)
        self.assertEqual(self.app.read_workspace()['projects'],{})
        self.assertFalse((self.app.WORK/'models').exists())
        self.assertFalse((self.app.WORK/'media').exists())

    def test_rotation_restore_and_runtime(self):
        self.app.LOCAL_3D.mkdir()
        (self.app.LOCAL_3D/'weights').write_bytes(b'keep-installed-engine')
        self.populate('premier');self.upgrade('2.8.0')
        second=self.populate('second');self.upgrade('2.9.0')
        a=self.app
        with zipfile.ZipFile(a.RESCUE) as z:
            info=a.inspect_rescue(z)
            self.assertEqual(info['version'],'2.8.0')
            self.assertEqual(z.read('travail/state.json'),second)
            self.assertFalse(any(b'premier' in z.read(f) for f in z.namelist() if f.startswith('travail/')))
        self.assertEqual(a.restore_backup()['version'],'2.8.0')
        restored=load(self.base)
        self.assertEqual((restored.WORK/'state.json').read_bytes(),second)
        self.assertEqual((restored.WORK/'models'/'abcdef'/'model.glb').read_bytes(),b'3D mesh second')
        self.assertEqual((restored.LOCAL_3D/'weights').read_bytes(),b'keep-installed-engine')
        self.assertEqual(list(self.base.glob('*.zip')),[a.RESCUE])

    def test_failure_preserves_current_and_previous(self):
        self.populate('ancien');self.upgrade('2.8.0')
        a=self.app;work=self.populate('actif')
        old=a.RESCUE.read_bytes()
        real=os.replace
        for fail_dest in (a.BASE/'serveur_inkforge.py',a.RESCUE):
            fired=[]
            def fail(src,dest):
                if Path(dest)==fail_dest and not fired:
                    fired.append(True)
                    if fail_dest==a.RESCUE:
                        with zipfile.ZipFile(src) as z:a.inspect_rescue(z)
                    raise OSError('simulated disk failure')
                return real(src,dest)
            with patch.object(a.os,'replace',side_effect=fail):
                with self.assertRaises(OSError):a.install_zip(package('2.9.0'))
            self.assertTrue(fired)
            self.assertEqual(a.version_data()['version'],'2.8.0')
            self.assertEqual((a.WORK/'state.json').read_bytes(),work)
            self.assertEqual(a.RESCUE.read_bytes(),old)
            self.assertFalse(a.TRANSACTION.exists())
        with patch.object(a,'inspect_rescue',side_effect=ValueError('fault verifying candidate')):
            with self.assertRaises(ValueError):a.install_zip(package('2.9.0'))
        self.assertEqual(a.RESCUE.read_bytes(),old)
        a.RESCUE.write_bytes(b'damaged spare')
        with self.assertRaises(zipfile.BadZipFile):a.restore_backup()
        self.assertEqual((a.WORK/'state.json').read_bytes(),work)

    def test_first_failed_install_keeps_verified_rescue(self):
        a=self.app;old=self.populate('premier')
        real=os.replace;fired=[]
        def fail(src,dst):
            if not fired and dst==a.BASE/'INKFORGE.html':
                fired.append(True)
                raise OSError('fault')
            return real(src,dst)
        with patch.object(a.os,'replace',side_effect=fail):
            with self.assertRaises(OSError):a.install_zip(package('2.8.0'))
        with zipfile.ZipFile(a.RESCUE) as z:self.assertEqual(z.read('travail/state.json'),old)
        self.assertEqual((a.WORK/'state.json').read_bytes(),old)

    def test_interrupted_commit_recovered_at_restart(self):
        self.populate('ancien');self.upgrade('2.8.0');a=self.app
        state=self.populate('actif');spare=a.RESCUE.read_bytes()
        (self.base/'incoming.zip').write_bytes(package('2.9.0'))
        program="""import os
from pathlib import Path
import serveur_inkforge as a
replace=os.replace
def cut(src,dst):
    if Path(dst)==a.BASE/'version.json' and Path(src).parent.name=='new':os._exit(73)
    return replace(src,dst)
a.os.replace=cut
a.install_zip(Path('incoming.zip').read_bytes())"""
        proc=subprocess.run([sys.executable,'-c',program],cwd=self.base,check=False)
        self.assertEqual(proc.returncode,73)
        load(self.base).recover_transaction()
        self.assertEqual(a.version_data()['version'],'2.8.0')
        self.assertEqual(a.RESCUE.read_bytes(),spare)
        self.assertEqual((a.WORK/'state.json').read_bytes(),state)

    def test_concurrency_and_auto_update(self):
        a=self.app
        self.populate('ici')
        with self.assertRaises(a.ClientFailure):a.save_workspace(dict(a.EMPTY_WORK))
        payload=package('2.8.0')
        release={'version':'2.8.0','repo':'owner/repo','asset_id':1,'sha256':hashlib.sha256(payload).hexdigest()}
        with patch.object(a,'release_data',return_value=release),patch.object(a,'urlopen',side_effect=lambda *args,**opts:io.BytesIO(payload)):
            with a.working_operation():
                with self.assertRaises(a.ClientFailure):a.auto_install('2.8.0')
            with self.assertRaises(ValueError):a.auto_install('2.9.0')
            self.assertEqual(a.auto_install('2.8.0'),'2.8.0')
        self.assertEqual(a.backup_version(),'2.7.0')


if __name__=='__main__':
    unittest.main(verbosity=2)
