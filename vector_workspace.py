"""独立上传矢量的字段配色 工作区。"""
import hashlib
import json

import pandas as pd
import streamlit as st

from io_utils import read_vector
from vector_styles import PALETTE, STYLE_FIELDS, categories, styled_geojson


def render_vector_workspace():
    st.subheader('矢量字段配色')
    st.caption('无需运行周边分析。上传矢量后查看属性、按字段值指定颜色。')
    upload = st.file_uploader('上传待转换的矢量文件', type=['geojson', 'json', 'zip'], key='vector_upload')
    if upload is None:
        st.info('请选择一个 GeoJSON 文件；配色也支持包含完整配套文件的 Shapefile ZIP。')
        return
    data = upload.getvalue()
    identity = hashlib.sha256(data + upload.name.encode()).hexdigest()
    try:
        if st.session_state.get('vector_identity') != identity:
            for key in list(st.session_state):
                if key.startswith('vector_') and key != 'vector_upload':
                    del st.session_state[key]
            with st.spinner('读取矢量字段…'):
                frame = read_vector(data, upload.name)
            st.session_state.vector_frame = frame
            st.session_state.vector_identity = identity
        frame = st.session_state.vector_frame
        if frame.empty:
            st.error('文件没有要素，请选择包含数据的文件。')
            return
        fields = [c for c in frame.columns if c != frame.geometry.name]
        st.caption(f'{len(frame):,} 个要素 / {len(fields)} 个属性字段 / 源坐标系：{frame.crs}')
        st.dataframe(pd.DataFrame(frame[fields].head(100)), use_container_width=True, hide_index=True)
        st.info('奥维 10.6.2 样例导入中，点和面显示了预期颜色，但线颜色未按设置显示；线样式兼容性仍待完善。')
        if not fields:
            st.warning('没有可用于分类的属性字段。')
            return
        field = st.selectbox('选择分类字段', fields, key='vector_field')
        groups = categories(frame, field)
        palette_id = identity + ':' + field
        if st.session_state.get('vector_palette_id') != palette_id:
            st.session_state.vector_colors = {g['key']: PALETTE[i % len(PALETTE)] for i, g in enumerate(groups)}
            st.session_state.vector_palette_id = palette_id
        colors = st.session_state.vector_colors
        st.caption(f'共 {len(groups)} 类；同一字段值使用同一种颜色。默认颜色循环分配，可逐类修改。空值单独归类。')
        selected = st.selectbox('选择要设置颜色的字段值', range(len(groups)),
                                format_func=lambda i: f"{groups[i]['label']} [{groups[i]['type']}] — {groups[i]['count']} 个要素")
        group = groups[selected]
        color_key = 'vector_color_' + hashlib.sha256((palette_id + group['key']).encode()).hexdigest()
        colors[group['key']] = st.color_picker('该字段值的颜色', colors[group['key']], key=color_key)
        st.dataframe(pd.DataFrame([{'字段值': g['label'], '类型': g['type'], '数量': g['count'], '颜色': colors[g['key']]} for g in groups]), hide_index=True, use_container_width=True)
        left, right = st.columns(2)
        width = left.number_input('线宽', min_value=0.0, max_value=20.0, value=2.0, step=0.5)
        opacity = right.slider('面填充不透明度', 0.0, 1.0, 0.4, 0.05)
        conflicts = sorted(STYLE_FIELDS.intersection(fields))
        overwrite = st.checkbox('替换原文件的样式属性：' + '、'.join(conflicts)) if conflicts else False
        signature = json.dumps([identity, field, colors, width, opacity, overwrite], sort_keys=True)
        if st.session_state.get('vector_style_signature') != signature:
            st.session_state.pop('vector_geojson', None)
        if st.button('生成配色 GeoJSON', type='primary', disabled=bool(conflicts) and not overwrite):
            with st.spinner('生成配色文件…'):
                st.session_state.vector_geojson = styled_geojson(frame, field, colors, width, opacity, overwrite)
                st.session_state.vector_style_signature = signature
        if st.session_state.get('vector_geojson'):
            st.download_button('下载配色 GeoJSON', st.session_state.vector_geojson, 'styled_vector.geojson', 'application/geo+json')
    except Exception as exc:
        st.error(f'处理失败：{exc}')
