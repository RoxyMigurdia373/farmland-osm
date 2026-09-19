import logging
import pandas as pd

import streamlit as st

from analyzer import OUTPUT_FIELDS, ROAD_TYPES_ZH, analyze, classify_features, summarize, validate_geometry, repair_geometry
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

with st.expander("上传数据要求与分类规则（首次使用请阅读）", expanded=True):
    input_tab, class_tab, result_tab = st.tabs(["文件与字段要求", "道路分类对照", "分析与结果规则"])
    with input_tab:
        st.markdown("""
**使用步骤：**上传耕地图斑 → 上传道路、铁路或村庄地物 → 按需设置距离阈值 → 开始分析 → 下载结果。

| 上传项 | 文件格式 | 几何与属性要求 |
| --- | --- | --- |
| 耕地图斑（一个文件） | Shapefile ZIP、GeoJSON / JSON | 必须为 Polygon / MultiPolygon 面；无必填属性字段，保留原属性 |
| 周边地物（可多文件） | Shapefile ZIP、GeoJSON / JSON | 支持点、线、面及其 Multi 类型；须有下表中的分类属性 |

**Shapefile 打包：**每套数据必须包含同名 `.shp`、`.shx`、`.dbf`、`.prj`，建议带 `.cpg` 声明中文编码。
例如 `路网.shp`、`路网.shx`、`路网.dbf`、`路网.prj`、`路网.cpg` 一起压缩为 `路网.zip`，不能只压缩 `.shp`。
ZIP 可含子目录或多套图层，程序会合并。单文件上传上限 500 MB；ZIP 解压后上限 2 GB、最多 10000 个文件。

**坐标系：**必须正确声明源坐标系；标准 GeoJSON 使用 WGS84 经纬度。不同文件可以使用不同坐标系，工具会统一投影。不能只改坐标系标签而不转换坐标。

**分类字段不是全部必填，满足一行条件即可；按以下顺序判断同一条地物：**

| 优先级 | 字段 | 有效内容示例 / 条件 | 归类 |
| --- | --- | --- | --- |
| 1 | `railway` | 有值，例如 `rail` | 铁路 |
| 2 | `highway` | 有值，例如 `tertiary`、`residential` | 公路（中文细分类见下一页） |
| 3 | `place` | 仅 `village`、`hamlet`、`town` | 村庄 |
| 4 | `landuse` | 仅 `residential` | 村庄 |

不匹配的地物会忽略，全部不匹配时停止分析。字段名兼容大小写、前后空格、`osm_` 前缀，也可读取 `tags` / `other_tags` 中的标准标签。
`railway` / `highway` 按“有值”判断，`no`、`0` 等也会被当作类型，请提前清理不适用的值。

**只有 `fclass` 怎么办？**目前不会直接按 `fclass`、`type` 或中文“道路类型”识别。
若是纯路网，且 `fclass` 值是 `motorway`、`primary`、`tertiary` 等 OSM 道路类型，可新增文本字段 `highway` 并复制对应值；混合图层请按地物分别填写相应分类字段。

**村庄名称（可选）：**按 `name:zh` → `name_zh` → `name` 优先读取，用于“紧邻XX村居民点…”；没有名称时写“村庄周边”。道路描述不显示具体路名。

**耕地原字段限制：**不能已有 `位置类型`、`地物子类`、`最近距离`、`位置描述`，请先重命名，避免覆盖原属性。
""")
    with class_tab:
        st.markdown("按项目约定将 `highway` 值转换为以下中文名称。连接线归入对应大类，不显示具体路名或英文类型。")
        st.table(pd.DataFrame([
            {"highway 值": key, "描述中的名称": value}
            for key, value in ROAD_TYPES_ZH.items()
        ]))
        st.caption("未列出的 highway 值统一表述为“公路”。这是本项目的名称映射，不是对国道、省道或公路技术等级的法定认定。")
    with result_tab:
        st.markdown("""
**几何修复：**侧边栏默认开启“自动修复无效几何”。修复自相交等问题，空几何、无法修复或不符合几何类型要求的记录会跳过，不进入结果。
页面显示各文件修复及跳过数量，可下载处理明细；行号从 1 开始，多图层 ZIP 按合并顺序编号。修复可能改变形状和面积，请复核。关闭修复后会严格校验并报错。

**最近地物：**对整个图斑与地物计算最短距离，而不是中心点距离。相交、接触或包含时距离为 0。
以米制 UTM 投影计算；失败时尝试 WGS84 局部等距投影并提示。大范围数据建议分地区分析。距离完全相同时优先铁路，其次公路，再次村庄。

**方位：**使用投影坐标中“地物中心 → 图斑中心”的主方向，分东、西、南、北侧。
这是中心相对方位，不是道路行驶方向的左/右侧；长弯曲道路、交叉或重叠图斑请人工复核。中心重合时当前按东侧处理。

**距离阈值：**默认不启用；启用后，超过阈值的位置类型为“无”，描述为“不在公路、铁路或村庄周边”，仍保留实际最近距离。
“紧邻”是描述模板用语，不代表已通过额外的邻近距离判断；需限制范围时请启用阈值。

| 场景 | 描述示例 |
| --- | --- |
| 道路 | 位于乡道东侧约85.20米 |
| 铁路 | 位于铁路西侧约120.50米 |
| 有村名 | 紧邻大同村居民点南侧约80.00米 |
| 无村名 | 村庄周边约80.00米 |
| 距离为 0 或不超过 0.005 米 | 位于乡道东侧 / 紧邻大同村居民点南侧；无村名时为“村庄周边” |

**导出：**GeoJSON 和 Shapefile 均为 WGS84。新增“位置类型、地物子类、最近距离、位置描述”，距离字段始终保留数值（包括 0），原始英文类别保留在“地物子类”。
Shapefile 使用 `loc_type`、`osm_sub`、`near_m`、`loc_desc` 短字段名，ZIP 内附中文字段映射；GeoJSON 保留中文列名。
DBF 文本超过 254 字节时不能导出 Shapefile，请使用 GeoJSON。

超过 5 万图斑时处理可能较慢；500 MB 上传上限不等于服务器内存容量，大数据建议拆分。
""")

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
