"""Assemble annual county results without dropping unprocessed original polygons."""
import pandas as pd
from ndvi_vector import CLASSES


def assemble_county(vector, results, id_field='plot_id', years=(2025, 2026)):
    if id_field not in vector or vector.crs is None:
        raise ValueError('原始矢量缺少ID或坐标系。')
    ids = vector[id_field].astype('string')
    if ids.isna().any() or ids.str.strip().eq('').any() or ids.duplicated().any():
        raise ValueError('原始图斑ID必须非空且唯一。')
    if results.duplicated(['plot_id', 'year']).any():
        raise ValueError('分类批次存在重复图斑年份。')
    if not results.plot_id.isin(ids).all():
        raise ValueError('分类ID不在原始县级矢量内。')
    if not results.classCode.isin(CLASSES).all():
        raise ValueError('分类代码无效。')
    out = vector.copy()
    report = {'total_plots': len(out), 'years': {}, 'method': 'NDVI阈值初筛，未经现场验证'}
    names = dict(classCode='code', className='state', valid_obs='nobs', last_obs='last',
                 ndviMax='max', ndviAmp='amp', ndviMeanGs='mean', provisional='partial')
    for year in years:
        rows = results.loc[results.year.eq(year)].set_index('plot_id')
        suffix = str(year)[-2:]
        matched = ids.isin(rows.index)
        for field, prefix in names.items():
            dest = f'{prefix}_{suffix}'
            if dest in out:
                raise ValueError(f'原始数据已有输出字段：{dest}')
            out[dest] = ids.map(rows[field]) if field in rows else None
            if field in ('className', 'last_obs'):
                out[dest] = out[dest].astype('string')
        out.loc[~matched, f'state_{suffix}'] = '待处理'
        # A missing job is NOT equivalent to an observed but cloud-obscured plot.
        out.loc[~matched, f'code_{suffix}'] = 0
        report['years'][str(year)] = {
            'processed': int(matched.sum()), 'pending': int((~matched).sum()),
            'classes': out[f'state_{suffix}'].value_counts().to_dict(),
        }
    return out, report
