"""Join reviewed browser classifications to original polygon geometries by explicit ID."""
import io
import json
import zipfile
import pandas as pd
from io_utils import export_shapefile

CLASSES = {1:'正常水稻',2:'疑似其他作物',3:'疑似撂荒地',4:'疑似未种植',5:'数据不足',6:'撂荒地（确认）'}
FIELDS = {'year':'ndvi_year','ndviMax':'ndvi_max','ndviAmp':'ndvi_amp','ndviMeanGs':'ndvi_mean','peakDoy':'peak_doy','className':'class_name','classCode':'class_code','reason':'reason','review':'review'}


def read_results(data):
    frame = pd.read_csv(io.BytesIO(data), dtype={'plot_id':str}, encoding='utf-8-sig')
    required = ['plot_id','year','ndviMax','ndviAmp','ndviMeanGs','peakDoy','className','classCode']
    missing = set(required)-set(frame.columns)
    if missing:
        raise ValueError('请上传网页导出的分类结果CSV，缺少字段：'+', '.join(sorted(missing)))
    frame = frame[required+[k for k in ['reason','review'] if k in frame]].copy()
    if frame.plot_id.isna().any() or frame.plot_id.str.strip().eq('').any():
        raise ValueError('分类结果存在空plot_id。')
    frame['plot_id'] = frame.plot_id.str.strip()
    for key in required[1:]:
        if key != 'className':
            frame[key] = pd.to_numeric(frame[key], errors='raise')
    if frame.year.isna().any() or (frame.year % 1 != 0).any() or not frame.year.between(2017,2100).all():
        raise ValueError('分类年份不合法。')
    if not frame.classCode.isin(CLASSES).all() or not frame.className.eq(frame.classCode.map(CLASSES)).all():
        raise ValueError('分类代码或分类名称不一致。')
    if frame.duplicated(['plot_id','year']).any():
        raise ValueError('同一plot_id和年份重复，请先清理重复批次。')
    return frame


def join_results(vector, results, id_field, year):
    if id_field not in vector:
        raise ValueError('矢量中不存在所选ID字段。')
    if vector.crs is None or vector.geometry.isna().any() or vector.geometry.is_empty.any():
        raise ValueError('矢量缺少坐标系或含空几何。')
    if not vector.geom_type.isin(['Polygon','MultiPolygon']).all() or not vector.is_valid.all():
        raise ValueError('矢量含非面或无效几何，请先修复后关联。')
    ids = vector[id_field].astype('string').str.strip()
    if ids.isna().any() or ids.eq('').any() or ids.duplicated().any():
        raise ValueError('矢量ID必须非空且唯一，不能按行号猜测关联。')
    selected = results.loc[results.year.eq(year)].copy()
    if selected.empty:
        raise ValueError('所选年份没有分类结果。')
    absent = selected.loc[~selected.plot_id.isin(ids), 'plot_id']
    if len(absent):
        raise ValueError(f'{len(absent)}个分类ID无法在矢量中匹配，例如：'+', '.join(absent.head(5)))
    # Only classify/export matching features: never mark unprocessed plots as abandoned.
    output = vector.loc[ids.isin(selected.plot_id)].copy()
    output['plot_id'] = ids.loc[output.index]
    selected = selected.set_index('plot_id')
    for key, short in FIELDS.items():
        if key in selected:
            if short in output:
                raise ValueError(f'原矢量已有字段{short}，请重命名后再导出以避免覆盖。')
            output[short] = output.plot_id.map(selected[key])
    return output, {'source_plots':len(vector), 'exported_plots':len(output),
                    'not_in_this_batch':len(vector)-len(output), 'year':int(year)}


def result_zip(frame, report):
    data = export_shapefile(frame)
    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, 'a', zipfile.ZIP_DEFLATED) as z:
        z.writestr('NDVI字段说明.json', json.dumps({v:k for k,v in FIELDS.items()},ensure_ascii=False,indent=2))
        z.writestr('分析范围与说明.json', json.dumps({**report, 'note':'NDVI阈值初筛，非现场确认；未进入本批分类的图斑未导出。几何来自上传矢量，输出WGS84。'},ensure_ascii=False,indent=2))
    return buf.getvalue()
