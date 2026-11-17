"""Standalone Python checks: no Autodesk Maya dependency required.
Run: python -m unittest discover -s tests -v
"""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ntools_release_installer_under_test', ROOT/'install.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class DummyWindow:
    def __init__(self, visible): self.visible=visible
    def isVisible(self): return self.visible


class FakeCmds:
    def __init__(self): self.windows=set(); self.queue=[]
    def window(self, name, exists=False): return name in self.windows
    def evalDeferred(self, callback): self.queue.append(callback)


class LiveUpdateTests(unittest.TestCase):
    def setUp(self):
        self.old_modules={}
        self.cmds=FakeCmds()
        self.old_fn=manager._maya
        manager._maya=lambda: (self.cmds,None)
    def tearDown(self):
        manager._maya=self.old_fn
        for name,prior in self.old_modules.items():
            if prior is None:sys.modules.pop(name,None)
            else:sys.modules[name]=prior
        if hasattr(sys,'_ntools_restart_required'):del sys._ntools_restart_required
        manager._UPDATE_BUSY=False
    def install_fake(self, suffix, **members):
        name='ntools.tools.'+suffix
        self.old_modules[name]=sys.modules.get(name)
        sys.modules[name]=types.SimpleNamespace(**members)
        return name
    def test_detect_only_changed_tool(self):
        before={'tools':[{'module':'one'},{'module':'two'}], 'files':{
            'scripts/ntools/tools/one.py':'a','scripts/ntools/tools/two.py':'b'}}
        after={'tools':[{'module':'one'},{'module':'two'}], 'files':{
            'scripts/ntools/tools/one.py':'a','scripts/ntools/tools/two.py':'c'}}
        self.assertEqual(manager._changed_tool_modules(before,after),{'ntools.tools.two'})
    def test_closed_material_window_allows(self):
        name=self.install_fake('material_creator',_WINDOW=DummyWindow(False))
        self.assertEqual(manager._hot_update_blockers({name}),[])
    def test_open_material_window_blocks(self):
        name=self.install_fake('material_creator',_WINDOW=DummyWindow(True))
        self.assertIn('Material Creator',manager._hot_update_blockers({name})[0])
    def test_city_busy_blocks_without_closing_server(self):
        obj=types.SimpleNamespace(busy=True,worker_thread=None,win='MayaCityBuilderWindow',server=object())
        name=self.install_fake('maya_city_builder',_maya_city_builder=obj)
        self.assertTrue(manager._hot_update_blockers({name}))
    def test_city_closed_server_is_closed_only_after_user_confirms(self):
        flag=[]
        obj=types.SimpleNamespace(busy=False,worker_thread=None,win='MayaCityBuilderWindow',server=object(),dispose=lambda:flag.append(True))
        name=self.install_fake('maya_city_builder',_maya_city_builder=obj)
        self.assertEqual(manager._hot_update_blockers({name}),[])
        self.assertEqual(flag,[])
        manager._quiesce_closed_tools({name})
        self.assertEqual(flag,[True])
    def test_quadruped_open_blocks(self):
        self.cmds.windows.add('QQR2027_v24_WIN')
        name=self.install_fake('quadruped_quick_rig',WIN='QQR2027_v24_WIN')
        self.assertTrue(manager._hot_update_blockers({name}))
    def test_closed_sketchfab_workers_block_until_idle(self):
        class Thread:
            def is_alive(self):return True
        pool=types.SimpleNamespace(_threads={Thread()})
        name=self.install_fake('sketchfab_asset_browser',_browser=types.SimpleNamespace(isVisible=lambda:False,grid_pool=pool))
        self.assertTrue(manager._hot_update_blockers({name}))
    def test_update_busy_window_does_not_apply_files(self):
        old={'version':'1.0.10','files':{'scripts/ntools/tools/material_creator.py':'a'},'tools':[{'module':'material_creator'}]}
        new={'version':'1.0.11','files':{'scripts/ntools/tools/material_creator.py':'b'},'tools':[{'module':'material_creator'}]}
        name=self.install_fake('material_creator',_WINDOW=DummyWindow(True))
        with (mock.patch.object(manager,'_installed',return_value=old),
              mock.patch.object(manager,'_ui_snapshot'),
              mock.patch.object(manager,'_online',return_value=(new,{'x':b'1'})),
              mock.patch.object(manager,'_apply') as apply,
              mock.patch.object(manager,'_notify') as notify):
            manager.update()
            apply.assert_not_called()
            self.assertIn('Material Creator',notify.call_args[0][0])
            self.assertFalse(manager._UPDATE_BUSY)
            self.assertEqual(self.cmds.queue,[])
    def test_update_hot_activates_after_deferred_callback(self):
        old={'version':'1.0.10','files':{},'tools':[]}
        new={'version':'1.0.11','files':{},'tools':[]}
        with (mock.patch.object(manager,'_installed',side_effect=[old,new]),
              mock.patch.object(manager,'_ui_snapshot'),
              mock.patch.object(manager,'_online',return_value=(new,{})),
              mock.patch.object(manager,'_confirm',return_value=True),
              mock.patch.object(manager,'_apply',return_value=True) as apply,
              mock.patch.object(manager,'_activate_runtime',return_value=None) as activate,
              mock.patch.object(manager,'_sync_management_buttons',return_value='シェルフ：最新'),
              mock.patch.object(manager,'_notify') as notify):
            manager.update()
            apply.assert_called_once()
            self.assertEqual(len(self.cmds.queue),1)
            self.cmds.queue.pop()()
            activate.assert_called_once_with(set())
            self.assertIn('再起動は不要',notify.call_args[0][0])
            self.assertFalse(manager._UPDATE_BUSY)
            self.assertFalse(getattr(sys,'_ntools_restart_required',False))
    def test_atomic_file_swap_does_not_set_restart_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'ntools'
            root.mkdir()
            (root/'old.txt').write_text('old')
            old={'version':'1.0.10', 'tools':[], 'files':{}}
            with (mock.patch.object(manager,'_target',return_value=root),
                  mock.patch.object(manager,'_installed',return_value=old)):
                self.assertTrue(manager._apply({'version':'1.0.11'}, {'installer.py':b'new installer','version.json':b'{}'}))
                self.assertEqual((root/'installer.py').read_bytes(), b'new installer')
                self.assertFalse(getattr(sys,'_ntools_restart_required',False))
                backups=list(root.parent.glob('.ntools-backup-*'))
                self.assertEqual(len(backups),1)
                self.assertEqual((backups[0]/'old.txt').read_text(), 'old')

    def test_activate_evicts_only_changed_tool(self):
        name=self.install_fake('sketchfab_asset_browser',show=lambda:None)
        with mock.patch.object(manager.importlib,'reload',side_effect=lambda x:x):
            manager._activate_runtime({name})
        self.assertNotIn(name,sys.modules)


if __name__ == '__main__': unittest.main()
