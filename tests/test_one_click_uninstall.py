"""Uninstall safety tests without Maya; native Maya confirmation is simulated."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nt_uninstall_test', ROOT / 'install.py')
nt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nt)

class FakeCmds:
    def __init__(self, live=True, prefs=False):
        self.live = live
        self.prefs = prefs
        self.queue = []
        self.notifications = []
        self.choice = 'No'
    def evalDeferred(self, callback): self.queue.append(callback)
    def shelfLayout(self, name, exists=False):
        assert exists
        return self.live
    def optionVar(self, exists=None, q=None):
        if exists is not None:
            if exists == 'numShelves': return self.prefs
            return self.prefs and exists == 'shelfName1'
        if q == 'numShelves': return 1
        if q == 'shelfName1': return 'nTools'
        raise AssertionError(q)
    def confirmDialog(self, **kw):
        if kw.get('button') == ['Yes', 'No']: return self.choice
        self.notifications.append(kw['message'])
        return 'OK'

class FakeMel:
    def __init__(self, cmds, answer):
        self.cmds = cmds
        self.answer = answer
        self.calls=[]
    def eval(self, command):
        self.calls.append(command)
        if self.answer == 'Yes':
            self.cmds.live = False
            self.cmds.prefs = False
        return None

class OneClickUninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.target = self.parent / 'ntools'
        self.target.mkdir()
        (self.target / 'keep.txt').write_text('tool')
        self.cmds = FakeCmds()
        self.mel = FakeMel(self.cmds, 'Yes')
        self.patchers = [
            mock.patch.object(nt, '_maya', side_effect=lambda:(self.cmds,self.mel)),
            mock.patch.object(nt, '_target', return_value=self.target),
            mock.patch.object(nt, '_installed', return_value={'tools':[]}),
            mock.patch.object(nt, '_ui_snapshot', return_value=('Modeling',)),
            mock.patch.object(nt, '_shelf', return_value='top|nTools'),
            mock.patch.object(nt, '_owned_shelf', return_value=True),
            mock.patch.object(nt, '_hot_update_blockers', return_value=[]),
            mock.patch.object(nt, '_quiesce_closed_tools'),
            mock.patch.object(nt, '_shelf_path', return_value=self.parent/'shelf_nTools.mel'),
            mock.patch.object(nt, '_backup_ui', side_effect=self.backup_ui),
        ]
        for p in self.patchers:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patchers)])
        nt._UNINSTALL_BUSY = False
        self.addCleanup(lambda:setattr(nt,'_UNINSTALL_BUSY',False))
        self.addCleanup(lambda:sys.__dict__.pop('_ntools_restart_required',None))
    def backup_ui(self):
        p = self.parent / '.ntools-ui-backups' / 'trial'
        p.mkdir(parents=True)
        (p/'userPrefs.mel').write_text('original')
        return p
    def run_queue(self):
        self.assertEqual(len(self.cmds.queue),1)
        self.cmds.queue.pop(0)()
    def test_yes_native_delete_and_reversible_move(self):
        nt.uninstall_from_shelf()
        self.assertTrue(self.target.exists())  # Deferred: never delete own callback.
        self.run_queue()
        self.assertEqual(self.mel.calls,['deleteShelfTab "nTools";'])
        self.assertFalse(self.target.exists())
        b=list(self.parent.glob('.ntools-uninstalled-*'))
        self.assertEqual(len(b),1)
        self.assertEqual((b[0]/'keep.txt').read_text(),'tool')
        self.assertTrue(getattr(sys,'_ntools_restart_required',False))
        self.assertFalse(nt._UNINSTALL_BUSY)
    def test_no_keeps_package_and_drops_temp_backup(self):
        self.mel.answer = 'No'
        nt.uninstall_from_shelf();self.run_queue()
        self.assertTrue(self.target.exists())
        self.assertFalse(list(self.parent.glob('.ntools-uninstalled-*')))
        self.assertFalse((self.parent/'.ntools-ui-backups'/'trial').exists())
        self.assertFalse(nt._UNINSTALL_BUSY)
    def test_busy_tools_block_before_confirmation(self):
        with mock.patch.object(nt,'_hot_update_blockers', return_value=['Sketchfab open']):
            nt.uninstall_from_shelf();self.run_queue()
        self.assertEqual(self.mel.calls,[])
        self.assertTrue(self.target.exists())
        self.assertIn('Sketchfab open',self.cmds.notifications[-1])
    def test_unknown_shelf_button_blocks(self):
        with mock.patch.object(nt,'_owned_shelf',return_value=False):
            nt.uninstall_from_shelf();self.run_queue()
        self.assertEqual(self.mel.calls,[])
        self.assertTrue(self.target.exists())
    def test_stale_file_blocks_python_removal(self):
        (self.parent/'shelf_nTools.mel').write_text('stale')
        nt.uninstall_from_shelf();self.run_queue()
        self.assertTrue(self.target.exists())
        self.assertIn('登録が残っています',self.cmds.notifications[-1])
    def test_files_only_no_is_inert(self):
        self.cmds.live=False
        self.cmds.choice='No'
        nt.uninstall();self.run_queue()
        self.assertTrue(self.target.exists())
        self.assertEqual(self.mel.calls,[])
    def test_files_only_yes_moves_package(self):
        self.cmds.live=False
        self.cmds.choice='Yes'
        nt.uninstall();self.run_queue()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.mel.calls,[])
    def test_rapid_multiple_clicks_schedule_once(self):
        nt.uninstall_from_shelf();nt.uninstall_from_shelf()
        self.assertEqual(len(self.cmds.queue),1)
        self.run_queue()
        self.assertFalse(nt._UNINSTALL_BUSY)

if __name__=='__main__':unittest.main()
