import io
import unittest
import zipfile
import geopandas as gpd
from shapely.geometry import Point, MultiPoint, box
from io_utils import export_shapefile, read_vector
from analyzer import classify_features


class MixedExportTests(unittest.TestCase):
    def test_village_points_and_polygons_roundtrip(self):
        frame = gpd.GeoDataFrame({
            'osm_id': ['1', '2', '3'], 'name': ['居民区', '城中街道', '村庄'],
            'landuse': ['residential', None, None], 'place': [None, 'town', 'village'],
        }, geometry=[box(112, 23, 112.01, 23.01), Point(112.678581, 23.3637555),
                     MultiPoint([(112.1, 23.1), (112.2, 23.2)])], crs=4326)
        data = export_shapefile(frame)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.shp')]), 3)
        loaded = read_vector(data, 'villages.zip')
        self.assertEqual(len(loaded), 3)
        self.assertEqual(set(loaded['name']), set(frame['name']))
        self.assertEqual(set(loaded.geom_type), set(frame.geom_type))
        self.assertEqual(classify_features(loaded)['位置类型'].tolist(), ['村庄'] * 3)
