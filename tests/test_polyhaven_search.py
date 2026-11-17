# -*- coding: utf-8 -*-
"""Headless regression tests for v5.4.2+ single active-tab search field."""
import ast
from pathlib import Path
import re
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'scripts'/'ntools'/'tools'/'polyhaven_asset_browser.py'
TREE=ast.parse(SOURCE.read_text(encoding='utf-8'))
NODE=next(x for x in ast.walk(TREE) if isinstance(x,ast.ClassDef) and x.name=='NativeBrowser')
NAMES={'_quiet_text','_quiet_choice','_online_category','_local_category',
       '_shared_search_changed','_shared_category_changed','reset_page','rebuild_online'}
methods=[m for m in NODE.body if isinstance(m,ast.FunctionDef) and m.name in NAMES]
assert len(methods)==len(NAMES), 'Search test methods no longer match the UI'
code=compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='SearchHarness',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])),str(SOURCE),'exec')

class Signal:
    def __init__(self):self.handlers=[]
    def connect(self,cb):self.handlers.append(cb)
    def emit(self,*args):
        for cb in self.handlers:cb(*args)

class Text:
    def __init__(self,txt=''):self.v=txt;self.blocked=False;self.textChanged=Signal()
    def text(self):return self.v
    def setText(self,v):
        self.v=v
        if not self.blocked:self.textChanged.emit(v)
    def blockSignals(self,on):prev=self.blocked;self.blocked=on;return prev

class Combo:
    def __init__(self,items):self.items=items;self.i=0;self.blocked=False;self.currentIndexChanged=Signal()
    def currentText(self):return self.items[self.i]
    def findText(self,v):return self.items.index(v) if v in self.items else -1
    def setCurrentIndex(self,i):
        self.i=i
        if not self.blocked:self.currentIndexChanged.emit(i)
    def blockSignals(self,on):prev=self.blocked;self.blocked=on;return prev

class Item:
    def __init__(self,title):self.title=title;self.props={}
    def setData(self,key,value):self.props[key]=value
    def setToolTip(self,value):pass
    def data(self,key):return self.props[key]

class List:
    def __init__(self):self.items=[]
    def clear(self):self.items=[]
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def setCurrentRow(self,i):pass

class Label:
    def setText(self,v):self.value=v
    def setEnabled(self,v):self.enabled=v

class Future:
    def cancel(self):pass

class QtCore:
    class Qt:UserRole=32
class QtWidgets:QListWidgetItem=Item

scope=dict(QtCore=QtCore,QtWidgets=QtWidgets,re=re,ph_thumbnail=lambda *args:None)
exec(code,scope)
SearchHarness=scope['SearchHarness']

class OneSearchTests(unittest.TestCase):
    def make(self,tab=1):
        a=SearchHarness();a.search=Text();a.ph_search=Text()
        a.category=Combo(['All','3D','Plants','Surfaces'])
        a.ph_kind=Combo(['All','3D Models','Plants','Surfaces'])
        a.page=0;a.page_size=36;a.page_label=Label();a.prev_btn=Label();a.next_btn=Label()
        a.ph_list=List();a.thumb_jobs={};a.thumb_pool=type('Pool',(),{'submit':lambda self,*args:Future()})()
        a.cache=Path('/tmp');a.catalog={
            'fir_tree_01':dict(type=2,name='Fir Tree 01',tags='tree',download_count=4),
            'stone_rock':dict(type=2,name='Stone Rock',tags='rock',download_count=3),
            'forest_hdri':dict(type=0,name='Forest HDRI',tags='forest sunset',download_count=2),
            'wood_surface':dict(type=1,name='Wood Surface',tags='wood',download_count=1),
        }
        a.hdri_mode=lambda:tab==2
        a.online=lambda:tab in (1,2)
        a.on_selected=lambda:None
        a.rebuild=lambda:setattr(a,'local_updated',True)
        a.ph_search.textChanged.connect(a._shared_search_changed)
        a.ph_kind.currentIndexChanged.connect(a._shared_category_changed)
        return a
    def ids(self,a):return [x.data(QtCore.Qt.UserRole) for x in a.ph_list.items]
    def test_online_search_single_line(self):
        a=self.make();a.ph_search.setText('tree')
        self.assertEqual(a.search.text(),'tree')
        self.assertEqual(self.ids(a),['fir_tree_01'])
    def test_category_filters_models_without_duplicate_widgets(self):
        a=self.make();a.ph_kind.setCurrentIndex(1)
        self.assertEqual(a.category.currentText(),'3D')
        self.assertEqual(set(self.ids(a)),{'fir_tree_01','stone_rock'})
    def test_search_preserves_terms_when_switching_tabs(self):
        a=self.make();a.ph_search.setText('forest');a.hdri_mode=lambda:True
        a.reset_page()
        self.assertEqual(a.ph_search.text(),'forest')
        self.assertEqual(self.ids(a),['forest_hdri'])
    def test_local_search_mirrors_hidden_field(self):
        a=self.make(tab=0);a.ph_search.setText('wood')
        self.assertEqual(a.search.text(),'wood')
        self.assertTrue(a.local_updated)
    def test_clear_search_restores_assets(self):
        a=self.make();a.ph_search.setText('tree');a.ph_search.setText('')
        self.assertEqual(len(self.ids(a)),3)

if __name__=='__main__':unittest.main()
