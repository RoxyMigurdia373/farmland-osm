import unittest
import geopandas as gpd
from shapely.geometry import Polygon, Point, GeometryCollection, box
from analyzer import repair_geometry, validate_geometry, analyze, classify_features


class RepairTests(unittest.TestCase):
    def test_repair_preserves_attributes_and_drops_empty(self):
        frame = gpd.GeoDataFrame({'id': [1, 2, 3, 4, 5]}, geometry=[
            Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)]),
            None, Polygon(), Polygon([(0, 0), (1, 0), (2, 0), (0, 0)]), box(3, 3, 4, 4)
        ], crs=32650)
        result, report, issues = repair_geometry(frame, farmland=True)
        validate_geometry(result, farmland=True)
        self.assertEqual(result.id.tolist(), [1, 5])
        self.assertEqual(report, {'输入数': 5, '修复数': 1, '跳过数': 3, '保留数': 2})
        self.assertEqual([i['原始行号'] for i in issues], [1, 2, 3, 4])
        self.assertFalse(frame.geometry.iloc[0].is_valid)
        self.assertAlmostEqual(result.geometry.iloc[0].area, 2)

    def test_collection_and_all_empty(self):
        frame = gpd.GeoDataFrame(geometry=[GeometryCollection([box(0, 0, 1, 1), Point(2, 2)])], crs=4326)
        result, _, _ = repair_geometry(frame, farmland=True)
        self.assertEqual(result.geom_type.tolist(), ['Polygon'])
        empty = gpd.GeoDataFrame(geometry=[None], crs=4326)
        result, report, _ = repair_geometry(empty)
        self.assertTrue(result.empty)
        self.assertEqual(report['跳过数'], 1)

    def test_repaired_input_analysis(self):
        frame = gpd.GeoDataFrame({'id': [1, 2]}, geometry=[
            Polygon([(117, 27), (117.001, 27.001), (117.001, 27), (117, 27.001), (117, 27)]), None
        ], crs=4326)
        frame, _, _ = repair_geometry(frame, farmland=True)
        osm = gpd.GeoDataFrame({'place': ['village']}, geometry=[Point(117, 27)], crs=4326)
        result, _, _ = analyze(frame, classify_features(osm))
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['最近距离'], 0)
