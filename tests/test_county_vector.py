import unittest
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from county_vector import assemble_county


class CountyTests(unittest.TestCase):
    def test_keeps_every_original_geometry_and_distinguishes_pending(self):
        v = gpd.GeoDataFrame({'plot_id':['001','002','003']}, geometry=[box(i,0,i+.1,.1) for i in range(3)], crs=4326)
        r = pd.DataFrame({'plot_id':['001','002'], 'year':[2025,2025],
                          'classCode':[1,5], 'className':['正常水稻','数据不足']})
        out, report = assemble_county(v,r)
        self.assertEqual(len(out),3)
        self.assertEqual(out.code_25.tolist(),[1,5,0])
        self.assertEqual(out.state_26.tolist(),['待处理']*3)
        self.assertTrue(out.geometry.equals(v.geometry))
        self.assertEqual(report['years']['2025']['pending'],1)
        with self.assertRaises(ValueError):
            assemble_county(v,pd.concat([r,r]))
