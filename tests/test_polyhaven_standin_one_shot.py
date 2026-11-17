# -*- coding: utf-8 -*-
"""One-shot Stand-in UI behavior, without Maya or Qt dependencies.

Directly exercises methods extracted from the distributed source AST.
"""
import ast
import importlib.util
from pathlib import Path
import unittest
from unittest import mock
import types

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/'scripts'/'ntools'/'tools'/'polyhaven_asset_browser.py'
spec=importlib.util.spec_from_file_location('polyhaven_test_oneshot',FILE)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
TREE=ast.parse(FILE.read_text(encoding='utf-8'))

def method(cls,name):
    node=next(n for n in ast.walk(TREE) if isinstance(n,ast.ClassDef) and n.name==cls)
    fn=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name==name)
    compiled=compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(FILE),'exec')
    ns=dict(mod.__dict__)
    exec(compiled,ns)
    return ns[name]

class Check:
    def __init__(self,val=False):self.val=val;self.changes=[]
    def isChecked(self):return self.val
    def setChecked(self,x):self.val=bool(x);self.changes.append(bool(x))

class Button:
    def __init__(self):self.enabled=None
    def setEnabled(self,v):self.enabled=v

class StandInOneShotTests(unittest.TestCase):
    def test_switching_assets_resets_manual_choice_but_refresh_does_not(self):
        fake=types.SimpleNamespace(proxy=Check(),split_standin=Check(),_standin_selection_key=None)
        method('AssetBrowser','_reset_standin_for_selection')(fake,('online','fir'))
        fake.proxy.setChecked(True)
        method('AssetBrowser','_reset_standin_for_selection')(fake,('online','fir'))
        self.assertTrue(fake.proxy.isChecked())
        method('AssetBrowser','_reset_standin_for_selection')(fake,None)
        self.assertTrue(fake.proxy.isChecked())
        method('AssetBrowser','_reset_standin_for_selection')(fake,('online','rock'))
        self.assertFalse(fake.proxy.isChecked())
    def test_local_manual_import_is_one_shot(self):
        proxy=Check(True)
        asset=types.SimpleNamespace(name='Fir',meshes=['mesh'])
        out=[]
        fake=types.SimpleNamespace(
            proxy=proxy,split_standin=Check(),_busy=False,
            selected=lambda:asset,
            settings=lambda:{'standin':proxy.isChecked(),'lod':1,'family':None},
            mapping=object(),log=out.append,
            import_btn=Button(),status=types.SimpleNamespace(setText=lambda x:None),
        )
        with mock.patch.object(mod,'import_asset',side_effect=lambda a,s,*args:out.append('standin='+str(s['standin']))):
            method('AssetBrowser','run_import')(fake)
        self.assertIn('standin=True',out)
        self.assertFalse(proxy.isChecked())
    def test_local_heavy_warning_standin_does_not_stick(self):
        proxy=Check(False)
        asset=types.SimpleNamespace(name='Fir',meshes=['mesh'])
        out=[]
        fake=types.SimpleNamespace(
            proxy=proxy,split_standin=Check(),_busy=False,
            selected=lambda:asset,
            settings=lambda:{'standin':proxy.isChecked(),'lod':1,'family':None},
            mapping=object(),log=out.append,
            import_btn=Button(),status=types.SimpleNamespace(setText=lambda x:None),
        )
        with (mock.patch.object(mod,'choose_mesh',return_value='mesh'),
              mock.patch.object(mod,'heavy_asset_hint',return_value={'warn':True,'reason':['heavy']}),
              mock.patch.object(mod,'standin_warning',return_value='standin'),
              mock.patch.object(mod,'import_asset',side_effect=lambda a,s,*args:out.append(s['standin']))):
            method('AssetBrowser','run_import')(fake)
        self.assertIn(True,out)
        self.assertFalse(proxy.isChecked())
        self.assertNotIn(True,proxy.changes)
    def make_online(self,manual=False):
        proxy=Check(manual)
        submitted=[]
        fake=types.SimpleNamespace(
            proxy=proxy,split_standin=Check(),_busy=False,jobs=[],catalog={'fir':{'type':2}},
            online_slug=lambda:'fir',assign=Check(False),copy=Check(False),
            hdri_mode=lambda:False,
            snapshot_settings=lambda:{'standin':proxy.isChecked(),'hdri_res':2,'resolution':2,'lod':1,'family':None},
            cancel_btn=Button(),cancel=None,on_selected=lambda:None,log=lambda _:None,
            pool=types.SimpleNamespace(submit=lambda *args:submitted.append(args) or 'future'),
            cache=Path('/tmp/cache'),messages=types.SimpleNamespace(put=lambda msg:None),
        )
        return fake, submitted
    def test_online_manual_queued_choice_still_applies_but_ui_resets(self):
        fake,submitted=self.make_online(manual=True)
        with mock.patch.object(mod,'confirm_project_copy',return_value=True):
            method('NativeBrowser','start_poly')(fake,True)
        self.assertEqual(len(fake.jobs),1)
        self.assertTrue(fake.jobs[0][2]['standin'])
        self.assertFalse(fake.proxy.isChecked())
    def test_online_heavy_dialog_choice_applies_once_without_ticking_checkbox(self):
        fake,submitted=self.make_online(manual=False)
        with (mock.patch.object(mod,'confirm_project_copy',return_value=True),
              mock.patch.object(mod,'heavy_asset_hint',return_value={'warn':True,'reason':['heavy']}),
              mock.patch.object(mod,'standin_warning',return_value='standin')):
            method('NativeBrowser','start_poly')(fake,True)
        self.assertTrue(fake.jobs[0][2]['standin'])
        self.assertFalse(fake.proxy.isChecked())
        self.assertNotIn(True,fake.proxy.changes)
    def test_online_import_ready_resets_one_shot_checkbox(self):
        proxy=Check(True)
        fake=types.SimpleNamespace(proxy=proxy,split_standin=Check(),_busy=False,import_btn=Button(),
            on_selected=lambda:None,mapping=object(),log=lambda _:None)
        with mock.patch.object(mod,'import_asset') as called:
            method('NativeBrowser','import_ready')(fake,types.SimpleNamespace(name='Fir',meshes=['mesh']),{'standin':True},)
        self.assertFalse(proxy.isChecked())
        called.assert_called_once()

if __name__=='__main__':unittest.main()
