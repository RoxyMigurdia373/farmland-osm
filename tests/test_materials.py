import unittest
import geopandas as gpd
from shapely.geometry import box, Point, LineString
from materials import extraction_area, normalize_layer, extract_materials
from io_utils import combine_frames, read_vector, export_geojson
from analyzer import classify_features


class MaterialTests(unittest.TestCase):
    def test_layer_mapping_and_boundary(self):
        area, _ = extraction_area(gpd.GeoDataFrame(geometry=[box(112, 23, 112.01, 23.01)], crs=4326), 0)
        frames = []
        for layer, value in [('roads', 'tertiary'), ('railways', 'rail'), ('places', 'village'), ('landuse', 'residential'), ('buildings', 'residential')]:
            frame = gpd.GeoDataFrame({'fclass': [value, value]}, geometry=[Point(112.005, 23.005), Point(113,24)], crs=4326)
            frames.append(normalize_layer(frame, f'gis_osm_{layer}_free_1.shp'))
        output, _, _ = extract_materials(combine_frames(frames), area)
        self.assertEqual(len(output), 4)
        loaded = read_vector(export_geojson(output), 'result.geojson')
        self.assertEqual(len(classify_features(loaded)), 4)

    def test_preserves_crossing_line(self):
        area, _ = extraction_area(gpd.GeoDataFrame(geometry=[box(112, 23, 112.01, 23.01)], crs=4326), 0)
        line = LineString([(111.99, 23.005), (112.02, 23.005)])
        frame = gpd.GeoDataFrame({'highway': ['primary']}, geometry=[line], crs=4326)
        output, _, _ = extract_materials(frame, area)
        self.assertTrue(output.geometry.iloc[0].equals(line))
