import io
import json
import unittest
import zipfile

import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon
from streamlit.testing.v1 import AppTest

from io_utils import read_vector, export_shapefile
from vector_styles import categories, value_key, styled_geojson


class VectorStyleTests(unittest.TestCase):
    def frame(self):
        return gpd.GeoDataFrame({'类别': ['道路', '地块', None], '编号': [1, 2, 3]},
                               geometry=[Point(116, 39), LineString([(116, 39), (116.1, 39.1)]),
                                         Polygon([(116, 39), (116.1, 39), (116.1, 39.1), (116, 39)])], crs=4326)

    def test_types_and_null_are_distinct(self):
        self.assertEqual(len({value_key(v) for v in [1, '1', True, None, 'null']}), 5)
        self.assertEqual(value_key(float('nan')), value_key(None))
        self.assertEqual(value_key({'a': 1, 'b': 2}), value_key({'b': 2, 'a': 1}))

    def test_colors_preserve_attributes_geometries_and_crs(self):
        frame = self.frame().to_crs(3857)
        colors = dict(zip([g['key'] for g in categories(frame, '类别')], ['#FF0000', '#00FF00', '#0000FF']))
        data = styled_geojson(frame, '类别', colors, width=3, opacity=.6)
        features = json.loads(data)['features']
        self.assertEqual([f['properties']['fill'] for f in features], list(colors.values()))
        self.assertEqual(features[0]['properties']['类别'], '道路')
        self.assertIsNone(features[2]['properties']['类别'])
        self.assertAlmostEqual(features[0]['geometry']['coordinates'][0], 116)
        self.assertNotIn('fill', frame.columns)

    def test_conflict_requires_explicit_overwrite(self):
        frame = self.frame(); frame['fill'] = 'original'
        colors = {g['key']: '#123456' for g in categories(frame, '类别')}
        with self.assertRaises(ValueError): styled_geojson(frame, '类别', colors)
        self.assertEqual(json.loads(styled_geojson(frame, '类别', colors, overwrite=True))['features'][0]['properties']['fill'], '#123456')
        self.assertEqual(frame['fill'][0], 'original')

    def test_invalid_or_missing_color_and_options_rejected(self):
        frame = self.frame(); colors = {g['key']: '#123456' for g in categories(frame, '类别')}
        with self.assertRaises(ValueError): styled_geojson(frame, '类别', {})
        with self.assertRaises(ValueError): styled_geojson(frame, '类别', {k: 'red' for k in colors})
        with self.assertRaises(ValueError): styled_geojson(frame, '类别', colors, opacity=float('nan'))

    def test_geojson_shapefile_roundtrip_chinese_and_mixed_geometry(self):
        frame = self.frame()
        data = frame.to_json(ensure_ascii=False).encode()
        result = export_shapefile(read_vector(data, 'test.geojson'))
        with zipfile.ZipFile(io.BytesIO(result)) as z:
            self.assertEqual(len([n for n in z.namelist() if n.endswith('.shp')]), 3)
            mapping = json.loads(z.read('字段映射.json'))
        restored = read_vector(result, 'result.zip')
        self.assertEqual(len(restored), 3)
        self.assertEqual(set(restored[mapping['类别']].dropna()), {'道路', '地块'})

    def test_workspace_flow_and_stale_download_invalidation(self):
        source = '''
import streamlit as st
from unittest.mock import patch
from vector_workspace import render_vector_workspace
class Upload:
    name = 'sample.geojson'
    def getvalue(self):
        return b'{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"kind":"A"},"geometry":{"type":"Point","coordinates":[116,39]}}]}'
with patch.object(st, 'file_uploader', return_value=Upload()):
    render_vector_workspace()
'''
        app = AppTest.from_string(source).run()
        self.assertEqual(len(app.exception), 0)
        app.button[0].click().run()
        self.assertIn('vector_geojson', app.session_state)
        app.slider[0].set_value(.8).run()
        self.assertNotIn('vector_geojson', app.session_state)
        self.assertEqual(len(app.exception), 0)
