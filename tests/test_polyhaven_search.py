"""Headless regression tests for PolyHaven's synchronized catalog search.
Run: python tests/test_polyhaven_search.py
No Maya/PySide required: loads only the UI methods under test from AST.
"""
import ast
from pathlib import Path
import re

SRC = Path(__file__).resolve().parents[1]/'scripts/ntools/tools/polyhaven_asset_browser.py'
TREE = ast.parse(SRC.read_text(encoding='utf8'))
cls = next(c for outer in ast.walk(TREE) if isinstance(outer,ast.ClassDef) for c in [outer] if c.name=='NativeBrowser')
NAMES = {'_quiet_text','_quiet_choice','_online_category','_local_category',
         '_top_search_changed','_online_search_changed','_top_kind_changed',
         '_online_kind_changed','source_changed','reset_page','rebuild_online'}
methods = [m for m in cls.body if isinstance(m,ast.FunctionDef) and m.name in NAMES]
assert len(methods)==len(NAMES)
CODE = compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='SearchHarness',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])),str(SRC),'exec')

class Signal:
    def __init__(self):self.callbacks=[]
    def connect(self,fn):self.callbacks.append(fn)
    def emit(self,*args):
        for cb in self.callbacks:cb(*args)

class Text:
    def __init__(self,default=''):
        self.v=default;self.blocked=False;self.textChanged=Signal()
    def text(self):return self.v
    def setText(self,value):
        if self.v==value:return
        self.v=value
        if not self.blocked:self.textChanged.emit(value)
    def blockSignals(self,b):old=self.blocked;self.blocked=b;return old

class Combo:
    def __init__(self,items):self.items=items;self.current=0;self.blocked=False;self.currentIndexChanged=Signal();self.enabled=True;self.visible=True
    def currentText(self):return self.items[self.current]
    def findText(self,v):return self.items.index(v) if v in self.items else -1
    def setCurrentIndex(self,i):
        if self.current==i:return
        self.current=i
        if not self.blocked:self.currentIndexChanged.emit(i)
    def blockSignals(self,b):old=self.blocked;self.blocked=b;return old
    def setEnabled(self,on):self.enabled=on
    def setVisible(self,on):self.visible=on

class Tab:
    def __init__(self):self.i=1
    def currentIndex(self):return self.i

class Label:
    def __init__(self):self.v='';self.enabled=None
    def setText(self,v):self.v=v
    def setEnabled(self,v):self.enabled=v

class Item:
    def __init__(self,name):self.name=name;self.data_map={}
    def setData(self,role,value):self.data_map[role]=value
    def setToolTip(self,text):self.tooltip=text
    def data(self,role):return self.data_map[role]

class List:
    def __init__(self):self.items=[];self.selected=None
    def clear(self):self.items=[];self.selected=None
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def setCurrentRow(self,i):self.selected=i

class FakeFuture:
    def cancel(self):pass

class Pool:
    def submit(self,*args):return FakeFuture()

class Layout:
    def addWidget(self,*args):pass

class StubWidget:
    def show(self):pass

class QtWidgets:
    QListWidgetItem=Item

class QtCore:
    class Qt:
        UserRole=32

namespace={'QtWidgets':QtWidgets,'QtCore':QtCore,'re':re,'ph_thumbnail':lambda *args:None}
exec(CODE,namespace)
SearchHarness=namespace['SearchHarness']

def build():
    a=SearchHarness();a.native_ready=True;a.tabs=Tab();a.search=Text();a.ph_search=Text()
    a.category=Combo(['All','3D','Surfaces','Plants']);a.ph_kind=Combo(['All','3D Models','Plants','Surfaces'])
    a.ph_list=List();a.page_label=Label();a.prev_btn=Label();a.next_btn=Label();a.page=0;a.page_size=36
    a.thumb_jobs={};a.thumb_pool=Pool();a.cache=None;a.online_content=StubWidget();a.online_layout=Layout();a.hdri_layout=Layout();a.catalog_job=None
    a.catalog={
        'fir_tree_01':{'type':2,'name':'Fir Tree 01','tags':['fir','tree'],'category':'plants','description':'green tree','download_count':600},
        'rock_stone':{'type':2,'name':'Rock Stone','tags':['rock'],'description':'rock','download_count':500},
        'brown_wood':{'type':1,'name':'Brown Wood','tags':['wood'],'description':'wood surface','download_count':400},
        'forest_sunset':{'type':0,'name':'Forest Sunset HDRI','tags':['forest','sunset'],'description':'sunset lighting','download_count':300},
    }
    a.rebuild=lambda *_:setattr(a,'local_rebuilds',getattr(a,'local_rebuilds',0)+1)
    a.on_selected=lambda *_:None
    a.online=lambda : a.tabs.currentIndex() in (1,2)
    a.hdri_mode=lambda : a.tabs.currentIndex()==2
    a.load_catalog=lambda *_:None
    a.search.textChanged.connect(a._top_search_changed)
    a.ph_search.textChanged.connect(a._online_search_changed)
    a.ph_search.textChanged.connect(a.reset_page)
    a.category.currentIndexChanged.connect(a._top_kind_changed)
    a.ph_kind.currentIndexChanged.connect(a._online_kind_changed)
    a.ph_kind.currentIndexChanged.connect(a.reset_page)
    return a

def ids(a):return [i.data(QtCore.Qt.UserRole) for i in a.ph_list.items]

# 1. Top search changes online list and synchronizes secondary input.
a=build();a.search.setText('tree')
assert a.ph_search.text()=='tree' and ids(a)==['fir_tree_01'],ids(a)
assert '1 assets' in a.page_label.v
# 2. Change inner search and update the top search without feedback loops.
a.ph_search.setText('rock')
assert a.search.text()=='rock' and ids(a)==['rock_stone']
# 3. Top category maps 3D to the online 3D Models filter.
a.search.setText('')
a.category.setCurrentIndex(1)
assert a.ph_kind.currentText()=='3D Models' and set(ids(a))=={'fir_tree_01','rock_stone'}
# 4. Lower Plants category syncs to top and filters correctly.
a.ph_kind.setCurrentIndex(2)
assert a.category.currentText()=='Plants' and ids(a)==['fir_tree_01']
# 5. Tab to HDRI and search from the same primary input.
a.tabs.i=2;a.source_changed()
a.search.setText('sunset')
assert ids(a)==['forest_sunset'] and a.ph_search.text()=='sunset'
assert not a.category.enabled
# 6. Going back to local preserves the search and updates local list.
a.tabs.i=0;a.source_changed()
assert a.category.enabled and a.local_rebuilds==1
assert a.search.text()=='sunset'
# 7. Return to Poly Haven and clear global term; online results restored.
a.tabs.i=1;a.category.setCurrentIndex(0);a.search.setText('');a.source_changed()
assert len(ids(a))==3 and a.ph_search.text()==''
print('PASS: seven headless regression checks for global/online search, categories and tab changes')
