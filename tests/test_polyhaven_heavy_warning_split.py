# -*- coding: utf-8 -*-
"""Headless regression tests for one-shot ASS split in heavy-model warning."""
import importlib.util
import pathlib
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/'scripts'/'ntools'/'tools'/'polyhaven_asset_browser.py'
spec=importlib.util.spec_from_file_location('test_split_warning_module', SOURCE)
ph=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ph)

class FakeCheckBox:
    last = None
    def __init__(self,label,parent):
        self.label=label
        self.value=False
        self.tooltip=''
        FakeCheckBox.last=self
    def setChecked(self,v):self.value=bool(v)
    def isChecked(self):return self.value
    def setToolTip(self,text):self.tooltip=text

class FakeMessageBox:
    Warning=4;AcceptRole=0;DestructiveRole=1;RejectRole=2
    desired='standin'
    check_choice=None
    last=None
    def __init__(self,parent):
        self.buttons={};self.checkbox=None;self.details='';self.title='';self.heading=''
        FakeMessageBox.last=self
    def setIcon(self,icon):pass
    def setWindowTitle(self,title):self.title=title
    def setText(self,text):self.heading=text
    def setInformativeText(self,text):self.details=text
    def setCheckBox(self,checkbox):self.checkbox=checkbox
    def addButton(self,label,role):
        button=object()
        self.buttons[label]=button
        if role==self.AcceptRole:self.yes=button
        elif role==self.DestructiveRole:self.no=button
        elif role==self.RejectRole:self.cancel=button
        return button
    def setDefaultButton(self,button):pass
    def exec(self):
        if self.check_choice is not None:self.checkbox.setChecked(self.check_choice)
    def clickedButton(self):
        return {'standin':self.yes,'editable':self.no,'cancel':self.cancel}[self.desired]

class HeavyWarningSplitTests(unittest.TestCase):
    def setUp(self):
        self.fakeqt=SimpleNamespace(QMessageBox=FakeMessageBox,QCheckBox=FakeCheckBox)
        self.ctx=mock.patch.object(ph,'QtWidgets',self.fakeqt)
        self.ctx.start()
        FakeMessageBox.desired='standin'; FakeMessageBox.check_choice=None
    def tearDown(self):self.ctx.stop()
    def run_dialog(self,selection,checked=None,previous='single'):
        FakeMessageBox.desired=selection
        FakeMessageBox.check_choice=checked
        settings={'standin_split':previous}
        choice=ph.standin_warning(None,['50万三角形以上'],settings)
        return choice, settings, FakeMessageBox.last
    def test_default_unchecked_and_single_ass(self):
        choice,settings,window=self.run_dialog('standin')
        self.assertEqual(choice,'standin')
        self.assertFalse(window.checkbox.isChecked())
        self.assertEqual(settings['standin_split'],'single')
        self.assertIn('一つのアセットに複数の木や草',window.details)
        self.assertEqual(window.checkbox.label,'Separate independent trees / groups into ASS')
    def test_checked_yields_auto_split_for_one_import(self):
        choice,settings,_=self.run_dialog('standin',True)
        self.assertEqual(choice,'standin')
        self.assertEqual(settings['standin_split'],'auto')
        choice2,next_settings,_=self.run_dialog('standin')
        self.assertEqual(next_settings['standin_split'],'single')
    def test_editable_ignores_checkbox(self):
        choice,settings,_=self.run_dialog('editable',True)
        self.assertEqual(choice,'editable')
        self.assertEqual(settings['standin_split'],'single')
    def test_cancel_ignores_checkbox(self):
        choice,settings,_=self.run_dialog('cancel',True)
        self.assertEqual(choice,'cancel')
        self.assertEqual(settings['standin_split'],'single')
    def test_manual_advanced_choice_visible_initially(self):
        _,settings,win=self.run_dialog('standin',previous='auto')
        self.assertTrue(win.checkbox.isChecked())
        self.assertEqual(settings['standin_split'],'auto')
    def test_can_opt_out_even_if_advanced_preset(self):
        _,settings,win=self.run_dialog('standin',checked=False,previous='auto')
        self.assertFalse(win.checkbox.isChecked())
        self.assertEqual(settings['standin_split'],'single')
    def test_paths_capture_settings_for_local_online_post_import(self):
        text=SOURCE.read_text(encoding='utf-8')
        # The UI must write to the dict used by each of the different flows.
        self.assertIn("standin_warning(self,hint['reason'],settings)",text)
        self.assertEqual(text.count("standin_warning(self,hint['reason'],s)"),2)
        self.assertIn("%(tri_count/10000)],settings)",text)
        self.assertIn("self.split_standin.setChecked(False)  # Do not carry split-ASS into the next asset.",text)

if __name__=='__main__':unittest.main()
