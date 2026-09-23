import unittest
import geopandas as gpd
from shapely.geometry import box, LineString
from analyzer import analyze, classify_features, ROAD_TYPES_ZH
from io_utils import export_shapefile, read_vector


class RangeTests(unittest.TestCase):
    def test_ranges_centers_and_export(self):
        land = gpd.GeoDataFrame(geometry=[box(500000, 2600000, 500010, 2600010)], crs=32649)
        osm = gpd.GeoDataFrame({'highway': ['primary_link']}, geometry=[
            LineString([(500310,2600000),(500310,2600010)])], crs=32649)
        result, _, _ = analyze(land, classify_features(osm), threshold=100,
                               dual_range=True, center_coords=True)
        row = result.iloc[0]
        self.assertEqual(row['位置类型'], '无')
        self.assertEqual(row['200米位置类型'], '无')
        self.assertTrue(gpd.pd.isna(row['200米最近距离']))
        self.assertEqual(row['500米位置描述'], '省道旁')
        self.assertAlmostEqual(row['500米最近距离'], 300, places=2)
        expected = gpd.GeoSeries([land.geometry.iloc[0].centroid], crs=32649).to_crs(4326).iloc[0]
        self.assertAlmostEqual(row['中心经度'], expected.x, places=7)
        self.assertAlmostEqual(row['中心纬度'], expected.y, places=7)
        loaded = read_vector(export_shapefile(result), 'result.zip')
        self.assertIn('center_lon', loaded)
        self.assertEqual(loaded.iloc[0]['r500_desc'], '省道旁')
        self.assertEqual(ROAD_TYPES_ZH['trunk_link'], '国道')
        self.assertEqual(ROAD_TYPES_ZH['residential'], '村道')
