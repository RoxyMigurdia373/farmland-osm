import io
import json
import unittest
import zipfile
from unittest.mock import patch

import geopandas as gpd
from shapely.geometry import Point, LineString, box

from analyzer import analyze, classify_features, validate_geometry
from io_utils import export_geojson, export_shapefile, read_vector


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.land = gpd.GeoDataFrame({"地块编号": [1, 2]}, geometry=[box(500000, 3000000, 500010, 3000010),
                                    box(500100, 3000000, 500110, 3000010)], crs=32650)
        self.osm = gpd.GeoDataFrame({"railway": ["rail", None], "highway": [None, "primary"]},
                                   geometry=[LineString([(500020, 2999900), (500020, 3000200)]),
                                             LineString([(499990, 2999900), (499990, 3000200)])], crs=32650)

    def test_classification(self):
        frame = gpd.GeoDataFrame({" Railway ": ["rail", None, None, None, None],
                                 "highway": ["primary", "secondary", None, None, None],
                                 "place": [None, None, "town", None, "city"],
                                 "other_tags": [None, None, None, '"landuse"=>"residential"', None]},
                                geometry=[Point(117, 27)] * 5, crs=4326)
        result = classify_features(frame)
        self.assertEqual(result["位置类型"].tolist(), ["铁路", "公路", "村庄", "村庄"])

    def test_distance_and_threshold(self):
        result, _, _ = analyze(self.land, classify_features(self.osm), threshold=50, chunk_size=1)
        self.assertEqual(result["位置类型"].tolist(), ["铁路", "无"])
        self.assertAlmostEqual(result["最近距离"].iloc[0], 10, places=2)
        self.assertAlmostEqual(result["最近距离"].iloc[1], 80, places=2)
        self.assertEqual(result["地块编号"].tolist(), [1, 2])

    def test_exact_tie_and_intersection(self):
        osm = self.osm.copy()
        osm.geometry = [self.land.geometry.iloc[0], self.land.geometry.iloc[0]]
        result, _, _ = analyze(self.land, classify_features(osm), threshold=0)
        self.assertEqual(result.iloc[0]["位置类型"], "铁路")
        self.assertEqual(result.iloc[0]["最近距离"], 0)

    def test_fallback(self):
        with patch.object(gpd.GeoDataFrame, "estimate_utm_crs", side_effect=RuntimeError("test")):
            result, warnings, crs = analyze(self.land, classify_features(self.osm))
        self.assertTrue(warnings)
        self.assertIn("aeqd", crs)
        self.assertAlmostEqual(result.iloc[0]["最近距离"], 10, delta=0.1)

    def test_exports(self):
        result, _, _ = analyze(self.land, classify_features(self.osm))
        geojson = export_geojson(result)
        self.assertIn("位置描述", json.loads(geojson)["features"][0]["properties"])
        loaded_json = read_vector(geojson, "result.geojson")
        self.assertEqual(loaded_json.crs.to_epsg(), 4326)
        zipped = export_shapefile(result)
        with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
            self.assertTrue({"result.shp", "result.shx", "result.dbf", "result.prj", "result.cpg"}.issubset(archive.namelist()))
        loaded = read_vector(zipped, "result.zip")
        self.assertEqual(loaded["loc_type"].tolist(), result["位置类型"].tolist())
        self.assertEqual(loaded["loc_desc"].tolist(), result["位置描述"].tolist())
        self.assertEqual(loaded.crs.to_epsg(), 4326)

    def test_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "面|Polygon"):
            validate_geometry(self.osm, farmland=True)
        with self.assertRaises(ValueError):
            read_vector(b"not json", "bad.geojson")
        with self.assertRaises(ValueError):
            analyze(self.land, classify_features(self.osm), threshold=-1)
        missing_crs = self.land.copy().set_crs(None, allow_override=True)
        with self.assertRaisesRegex(ValueError, "坐标系"):
            validate_geometry(missing_crs)

    def test_zip_safety_and_components(self):
        for name, expected in [("../bad.shp", "不安全"), ("test.shp", "缺少")]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(name, b"fake")
            with self.assertRaisesRegex(ValueError, expected):
                read_vector(buffer.getvalue(), "test.zip")


if __name__ == "__main__":
    unittest.main()
