import os
from pathlib import Path
import shutil
import subprocess
import uuid
import unittest


class SettingsTests(unittest.TestCase):
    def test_persistence_and_validation(self):
        shell = (r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt'
                 else shutil.which('sh'))
        workspace = Path(__file__).resolve().parents[1] / "build"
        root = workspace / ("settings-test-" + uuid.uuid4().hex)
        root.mkdir(parents=True)
        self.assertEqual(root.resolve().parent, workspace.resolve())
        self.addCleanup(shutil.rmtree, root)
        source = (Path(__file__).resolve().parents[1] / 'module/settings.sh').read_text()
        # Exercise the real script using an isolated state directory.
        source = source.replace('STATE=/data/adb/questlhsync-gxr', 'STATE=./state')
        (root / 'settings.sh').write_text(source, newline='\n')

        def run(*args):
            return subprocess.run([shell, './settings.sh', *args], cwd=root,
                                  text=True, capture_output=True)

        initial = run('get')
        self.assertEqual(initial.returncode, 0, initial.stderr)
        self.assertEqual(initial.stdout.strip(), '10000000')
        for value in ('1000000', '3000000', '5000000', '7900000', '10000000'):
            result = run('set', value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(run('get').stdout.strip(), value)
        for value in ('0', '999999', '10000001', '10100000', '5000001',
                      '999999999999999999', '-1', '1e7', '5;echo bad', '01000000'):
            self.assertNotEqual(run('set', value).returncode, 0, value)
            self.assertEqual(run('get').stdout.strip(), '10000000')
        (root / 'state/max-exposure-ns').write_text('corrupt\n')
        self.assertNotEqual(run('get').returncode, 0)


if __name__ == '__main__':
    unittest.main()
