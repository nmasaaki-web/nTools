"""Offline safety checks; no Maya required."""
import importlib.util
from pathlib import Path
import unittest

SOURCE=Path(__file__).resolve().parents[1] / 'scripts/ntools/tools/polyhaven_asset_browser.py'
spec=importlib.util.spec_from_file_location('polyhaven_safe_materials',SOURCE)
ph=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ph)

class SafeMaterials(unittest.TestCase):
    def setUp(self):
        self.keys=['fir_tree_01_bark','fir_tree_01_trunk_a','fir_tree_01_trunk_b','fir_tree_01_trunk_c','fir_tree_01_twig']

    def test_synthetic_sg_not_a_material_name(self):
        self.assertIsNone(ph.safe_auto_material_key(self.keys, ['fir_tree_01_a_LOD0SG1']))

    def test_model_name_a_does_not_mean_trunk_a(self):
        self.assertIsNone(ph.safe_auto_material_key(self.keys, ['Fir_Tree_01_a_LOD0Shape']))

    def test_tex_map_name_identifies_twig(self):
        self.assertEqual(ph.safe_auto_material_key(self.keys, ['fir_tree_01_twig_diff_2k']), 'fir_tree_01_twig')

    def test_clear_material_name_matches(self):
        self.assertEqual(ph.safe_auto_material_key(self.keys, ['fir_tree_01_trunk_b']), 'fir_tree_01_trunk_b')

    def test_one_set_is_unambiguous(self):
        self.assertEqual(ph.safe_auto_material_key(['stone'], ['Material23']), 'stone')

    def test_no_sets_are_unresolved(self):
        self.assertIsNone(ph.safe_auto_material_key([], ['SG1']))

    def test_mapping_summary_no_qt(self):
        msgs=[]
        ph.mapping_summary({'_unresolved_materials':[('SG1','shape1'),('SG1','shape1')]},msgs.append)
        self.assertTrue(any('1 material assignment' in m for m in msgs))

if __name__=='__main__':unittest.main()
