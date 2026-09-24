"""Export browser classification results as polygon Shapefiles."""
import streamlit as st
from io_utils import read_vector
from ndvi_vector import read_results, join_results, result_zip

st.set_page_config(page_title='NDVI分类矢量导出',page_icon='🗺️',layout='wide')
st.title('NDVI分类结果 → 矢量导出')
st.write('在NDVI工作台导出分类结果CSV，再上传对应原始图斑，按唯一编号关联并下载Shapefile。')
st.info('此步骤的文件由网站服务器处理；不发送到GEE。保留原始图斑几何和属性，只导出当前年份已匹配的分类图斑。未分析图斑不会标为撂荒。')
st.caption('分类CSV需要plot_id、year、ndviMax、ndviAmp、ndviMeanGs、peakDoy、className、classCode。矢量编号必须与CSV的plot_id完全一致，前导零需保留。没有编号时请使用提取前保存的编号矢量，不能根据行顺序猜测。')
a,b=st.columns(2)
with a:
    csvs=st.file_uploader('上传网页分类结果CSV（支持多个批次）',type=['csv'],accept_multiple_files=True)
with b:
    shp=st.file_uploader('上传对应图斑ZIP / GeoJSON',type=['zip','geojson','json'])
if csvs and shp:
    try:
        import pandas as pd
        results=pd.concat([read_results(f.getvalue()) for f in csvs],ignore_index=True)
        if results.duplicated(['plot_id','year']).any():
            raise ValueError('上传的多个CSV有重复图斑年份，请移除重复批次。')
        vector=read_vector(shp.getvalue(),shp.name)
        fields=[k for k in vector.columns if k!=vector.geometry.name]
        if not fields:
            raise ValueError('矢量没有可用于关联的编号字段。')
        id_field=st.selectbox('矢量中对应plot_id的字段',fields,index=fields.index('plot_id') if 'plot_id' in fields else 0)
        year=st.selectbox('导出年份',sorted(results.year.astype(int).unique()))
        if st.button('关联分类结果并生成SHP',type='primary'):
            with st.spinner('关联编号并生成矢量…'):
                output,report=join_results(vector,results,id_field,int(year))
                payload=result_zip(output,report)
            st.success(f"已匹配{report['exported_plots']:,}个图斑；原矢量另外{report['not_in_this_batch']:,}条不在本批结果中，不导出。")
            st.dataframe(output.groupby(['class_code','class_name']).size().rename('图斑数').reset_index(),hide_index=True)
            st.download_button('下载分类矢量 Shapefile ZIP',payload,f'ndvi_classification_{year}.zip','application/zip')
    except Exception as exc:
        st.error(str(exc))
