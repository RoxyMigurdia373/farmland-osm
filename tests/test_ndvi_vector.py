import unittest
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from ndvi_vector import read_results,join_results,result_zip
from io_utils import read_vector
class VectorTests(unittest.TestCase):
    def test_exact_join_roundtrip(self):
        v=gpd.GeoDataFrame({'plot_id':['002','001','003'],'old':[2,1,3]},geometry=[box(i,0,i+.1,.1) for i in range(3)],crs=4326)
        r=read_results(b'plot_id,year,ndviMax,ndviAmp,ndviMeanGs,peakDoy,className,classCode\n001,2025,.7,.5,.5,220,\xe6\xad\xa3\xe5\xb8\xb8\xe6\xb0\xb4\xe7\xa8\xbb,1\n')
        o,report=join_results(v,r,'plot_id',2025)
        self.assertEqual(o.old.tolist(),[1]);self.assertEqual(report['not_in_this_batch'],2)
        self.assertTrue(o.geometry.iloc[0].equals(v.geometry.iloc[1]))
        back=read_vector(result_zip(o,report),'result.zip')
        self.assertEqual(len(back),1);self.assertEqual(back.class_code.iloc[0],1)
        self.assertEqual(back.plot_id.iloc[0],'001')
        r.loc[0,'plot_id']='missing'
        with self.assertRaises(ValueError): join_results(v,r,'plot_id',2025)
    def test_duplicate_id_rejected(self):
        v=gpd.GeoDataFrame({'id':['a','a']},geometry=[box(0,0,1,1)]*2,crs=4326)
        with self.assertRaises(ValueError): join_results(v,pd.DataFrame({'year':[2025],'plot_id':['a']}),'id',2025)
if __name__=='__main__': unittest.main()
