# -*- coding: utf-8 -*-
"""Regression tests for rescan regression and unregistered USD node types."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/'scripts/ntools/tools/data_collector.py'
spec=importlib.util.spec_from_file_location('nTools_data_collector_rescan_test', FILE)
collector=importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class MockUi:
    def __init__(self):
        self.removed=[]
        self.rows=['oldrow']
        self.checks={'oldbox':False}
        self.active_parent='other_control'
        self.created=[]
        self.project=''
    def window(self,name,exists=False):
        assert name==collector.WINDOW
        return True
    def checkBox(self,*args,**kwargs):
        if kwargs.get('q'):
            return self.checks[args[0]]
        name='check'+str(len(self.created))
        self.checks[name]=kwargs.get('value')
        self.created.append(name)
        return name
    def columnLayout(self,*args,**kwargs):
        if kwargs.get('q'):
            return list(self.rows)
        return 'list'
    def deleteUI(self,name,*args,**kwargs):
        if name==collector.WINDOW:
            raise AssertionError('The rescan must never delete its own window')
        self.removed.append(name)
        self.rows=[]
    def setParent(self, *args,**kwargs):
        if kwargs.get('q'):return self.active_parent
        self.active_parent=args[0]
    def text(self,*args,**kwargs):
        if kwargs.get('e'):
            self.project=kwargs.get('label')
        return 'text'
    def rowLayout(self,*args,**kwargs):return 'row'


class RescanTests(unittest.TestCase):
    def test_rescan_keeps_window_and_selection(self):
        ui=MockUi()
        win=collector.CollectorWindow.__new__(collector.CollectorWindow)
        win.cmds=ui
        win.root=Path('/old')
        win.entries=[]
        win.list_layout='list'
        win.project_text='project_label'
        old={'key':'same','members':['/x'],'readonly':False,
             'kind':'texture','label':'file1','plug':'file1.fileTextureName',
             'status':'コピー可能','source':'/x'}
        new=dict(old)
        new['label']='file2'
        win.widgets=[(old,'oldbox')]
        with patch.object(collector,'scan',return_value=(Path('/new'),[new])):
            win.refresh()
        self.assertEqual(ui.removed,['oldrow'])
        self.assertEqual(len(win.widgets),1)
        self.assertFalse(ui.checks[win.widgets[0][1]])
        self.assertIn('/new',ui.project)
        self.assertEqual(ui.active_parent,'other_control')

    def test_new_rescan_item_checked_by_default(self):
        ui=MockUi()
        win=collector.CollectorWindow.__new__(collector.CollectorWindow)
        win.cmds=ui;win.root=None;win.entries=[];win.widgets=[]
        win.list_layout='list';win.project_text=None
        row={'key':'new','members':['/x'],'readonly':False,
             'kind':'texture','label':'newfile','plug':'new.fileTextureName',
             'status':'コピー可能','source':'/x'}
        with patch.object(collector,'scan',return_value=(Path('/new'),[row])):
            win.refresh()
        self.assertTrue(ui.checks[win.widgets[0][1]])

    def test_unsupported_pxr_type_not_queried(self):
        class FakeScanner:
            def __init__(self, project):self.project=project;self.searched=[]
            def workspace(self,**kw):return str(self.project)
            def allNodeTypes(self):return ['file','reference','cacheFile']
            def ls(self,**kw):
                node_type=kw.get('type')
                self.searched.append(node_type)
                if node_type in ('pxrUsdProxyShape','mayaUsdProxyShape'):
                    raise AssertionError('Unregistered USD node type was queried')
                return []
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp)
            (project/'workspace.mel').write_text('// workspace')
            fake=FakeScanner(project)
            _,result=collector.scan(fake)
            self.assertEqual(result,[])
            self.assertNotIn('pxrUsdProxyShape',fake.searched)
            self.assertNotIn('mayaUsdProxyShape',fake.searched)

if __name__=='__main__':unittest.main()
