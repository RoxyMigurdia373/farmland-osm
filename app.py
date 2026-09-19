import logging
import pandas as pd

import streamlit as st

from analyzer import OUTPUT_FIELDS, analyze, classify_features, summarize, validate_geometry, repair_geometry
from io_utils import combine_frames, export_geojson, export_shapefile, read_vector

st.set_page_config(page_title="耕地地块周边地物分析工具", page_icon="🌾", layout="wide")
st.title("耕地地块周边地物分析工具")
st.caption("离线空间分析 · 无需地图服务 · 距离单位：米")
st.info("本地运行时文件保留在本机；使用云端部署时，上传文件由该服务器处理。不会调用第三方地图服务。")


def clear_result():
    st.session_state.pop("analysis_result", None)


with st.sidebar:
    st.header("分析设置")
    enabled = st.checkbox("启用最大距离阈值", on_change=clear_result)
    threshold = st.number_input("最大距离（米）", min_value=0.0, value=1000.0, step=100.0,
                                disabled=not enabled, on_change=clear_result)
    st.caption("超过阈值的位置类型为“无”，仍保留真实最近距离。未启用时，每个地块均匹配最近地物。")
    st.caption("Shapefile 下载采用短英文列名，压缩包内含中文字段映射。")
    auto_repair = st.checkbox("自动修复无效几何", value=True, on_change=clear_result)
    st.caption("尝试修复自相交等问题；空几何和无法修复的记录会跳过，不进入结果。修复可能改变形状，请复核处理明细。")

left, right = st.columns(2)
with left:
    farmland_upload = st.file_uploader("上传耕地图斑（面矢量）", type=["zip", "geojson", "json"],
                                       on_change=clear_result)
with right:
    osm_uploads = st.file_uploader("上传 OSM 地物（可多选）", type=["zip", "geojson", "json"],
                                  accept_multiple_files=True, on_change=clear_result)

if st.button("开始分析", type="primary", disabled=farmland_upload is None or not osm_uploads):
    clear_result()
    try:
        repair_reports, repair_issues = [], []

        def prepare(frame, filename, farmland=False):
            if auto_repair:
                frame, report, issues = repair_geometry(frame, farmland=farmland)
                repair_reports.append({"文件": filename, **report})
                repair_issues.extend({"文件": filename, **issue} for issue in issues)
                st.write(f"{filename}：输入 {report['输入数']}，修复 {report['修复数']}，跳过 {report['跳过数']}，保留 {report['保留数']}。")
            if frame.empty:
                if farmland:
                    raise ValueError("耕地图斑修复后没有可用面几何，请检查源数据。")
                return frame
            validate_geometry(frame, farmland=farmland)
            return frame

        with st.status("正在读取数据…", expanded=True) as status:
            st.write("读取并检查耕地图斑…")
            farmland = read_vector(farmland_upload.getvalue(), farmland_upload.name)
            farmland = prepare(farmland, farmland_upload.name, farmland=True)
            if len(farmland) > 50000:
                st.warning("数据量较大，请耐心等待。将使用空间索引和分块查询；云端内存有限，必要时请拆分数据或本地运行。")
            st.write("读取 OSM 数据并分类地物…")
            classified = []
            for upload in osm_uploads:
                frame = read_vector(upload.getvalue(), upload.name)
                frame = prepare(frame, upload.name)
                if frame.empty:
                    continue
                selected = classify_features(frame)
                if not selected.empty:
                    classified.append(selected)
            if not classified:
                raise ValueError("分类后没有可用地物。请检查 railway、highway、place、landuse 属性字段；place 仅识别 village/hamlet/town，landuse 仅识别 residential。")
            features = combine_frames(classified)
            st.write(f"识别到 {len(features):,} 个公路、铁路或村庄地物，开始空间分析…")
            bar = st.progress(0.0)
            result, warnings, crs = analyze(farmland, features, threshold if enabled else None, bar.progress)
            st.write("正在生成下载文件…")
            geojson = export_geojson(result)
            shp = None
            try:
                shp = export_shapefile(result)
            except Exception as exc:
                warnings.append(f"Shapefile 导出失败，GeoJSON 仍可下载：{exc}")
            st.session_state.analysis_result = {
                "count": len(result), "summary": summarize(result), "preview": result[OUTPUT_FIELDS].head(100),
                "geojson": geojson, "shp": shp, "warnings": warnings, "crs": crs,
                "repair_reports": repair_reports, "repair_issues": repair_issues,
            }
            status.update(label="分析完成", state="complete", expanded=False)
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        logging.exception("空间分析失败")
        st.error(f"处理失败，请检查输入数据或服务器可用内存。详细信息：{exc}")
    if "analysis_result" not in st.session_state and repair_reports:
        st.dataframe(pd.DataFrame(repair_reports), hide_index=True)
        if repair_issues:
            st.download_button("下载几何处理明细 CSV", pd.DataFrame(repair_issues).to_csv(index=False).encode("utf-8-sig"),
                               "geometry_report.csv", "text/csv")

if "analysis_result" in st.session_state:
    saved = st.session_state.analysis_result
    st.success(f"分析完成！共处理 {saved['count']:,} 个耕地图斑。")
    st.caption(f"距离计算坐标系：{saved['crs']}；导出坐标系：WGS84（EPSG:4326）。")
    for message in saved["warnings"]:
        st.warning(message)
    if saved.get("repair_reports"):
        st.subheader("几何检查与修复")
        st.dataframe(pd.DataFrame(saved["repair_reports"]), hide_index=True)
        if saved.get("repair_issues"):
            st.warning("部分记录已修复或跳过；分析数量仅包含保留的图斑。请下载明细复核，行号从 1 开始（ZIP 多图层按合并后的顺序）。")
            st.download_button("下载几何处理明细 CSV", pd.DataFrame(saved["repair_issues"]).to_csv(index=False).encode("utf-8-sig"),
                               "geometry_report.csv", "text/csv")
    st.subheader("分类统计")
    st.dataframe(saved["summary"], hide_index=True, width="stretch")
    st.subheader("属性预览（前 100 行）")
    st.dataframe(saved["preview"], hide_index=True, width="stretch")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("下载 GeoJSON", saved["geojson"], "farmland_result.geojson", "application/geo+json")
    with col2:
        if saved["shp"] is not None:
            st.download_button("下载 Shapefile (zip)", saved["shp"], "farmland_result.zip", "application/zip")
