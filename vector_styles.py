"""按属性值生成 SimpleStyle GeoJSON；不假定所有 GIS 都读取样式字段。"""
import json
import math
import re

import pandas as pd

PALETTE = ['#245BD8', '#19856B', '#D68A16', '#A855A0', '#DB5D50', '#4B8BA8', '#7462BC', '#7B873C']
STYLE_FIELDS = {'stroke', 'stroke-width', 'stroke-opacity', 'fill', 'fill-opacity', 'marker-color'}


def value_key(value):
    """区分字符串、数值、布尔和空值，避免同名类别串色。"""
    if isinstance(value, (dict, list)):
        return 'json:' + json.dumps(value, ensure_ascii=False, sort_keys=True)
    if pd.isna(value):
        return 'null:'
    if hasattr(value, 'item'):
        value = value.item()
    return type(value).__name__ + ':' + json.dumps(value, ensure_ascii=False)


def categories(frame, field):
    if field not in frame or field == frame.geometry.name:
        raise ValueError('请选择有效的属性字段。')
    counts = frame[field].map(value_key).value_counts(sort=False)
    return [{'key': key, 'label': '空值' if key == 'null:' else key.split(':', 1)[1],
             'type': key.split(':', 1)[0], 'count': int(count)} for key, count in counts.items()]


def styled_geojson(frame, field, colors, width=2.0, opacity=0.4, overwrite=False):
    if frame.empty:
        raise ValueError('文件中没有可导出的要素。')
    groups = categories(frame, field)
    conflicts = STYLE_FIELDS.intersection(frame.columns)
    if conflicts and not overwrite:
        raise ValueError('原属性包含样式字段，请明确选择替换后再导出：' + '、'.join(sorted(conflicts)))
    if not math.isfinite(width) or not 0 <= width <= 20 or not math.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError('线宽应为 0–20，透明度应为 0–1。')
    for group in groups:
        color = colors.get(group['key'])
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', color):
            raise ValueError('每个字段值都需要有效的 #RRGGBB 颜色。')
    document = json.loads(frame.to_crs(4326).to_json(ensure_ascii=False, na='null', drop_id=True))
    # 从原始序列取键，避免 JSON 序列化改变属性类型后导致查色错误。
    for feature, value in zip(document['features'], frame[field]):
        color = colors[value_key(value)]
        feature['properties'].update({'stroke': color, 'stroke-width': float(width), 'stroke-opacity': 1.0,
                                      'fill': color, 'fill-opacity': float(opacity), 'marker-color': color})
    return json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
