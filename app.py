import logging
import pandas as pd

import streamlit as st

from analyzer import OUTPUT_FIELDS, ROAD_TYPES_ZH, analyze, classify_features, summarize, validate_geometry, repair_geometry
from io_utils import combine_frames, export_geojson, export_shapefile, read_vector
from materials import extraction_area, normalize_layer, extract_materials

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
    st.subheader("位置描述")
    show_direction = st.checkbox("显示方位", value=False, on_change=clear_result)
    show_distance = st.checkbox("显示距离", value=False, on_change=clear_result)
    st.caption("默认仅显示“乡道旁”“村道旁”等。方位、距离可分别勾选；0 米不显示距离。距离字段与阈值判断不受影响。")
    auto_repair = st.checkbox("自动修复无效几何", value=True, on_change=clear_result)
    st.caption("尝试修复自相交等问题；空几何和无法修复的记录会跳过，不进入结果。修复可能改变形状，请复核处理明细。")

st.caption("上传耕地图斑和周边地物，点击“开始分析”。首次使用可展开下方说明。")
with st.expander("使用说明 · 数据要求与分类规则", expanded=False):
    input_tab, class_tab, result_tab = st.tabs(["文件与字段要求", "道路分类对照", "分析与结果规则"])
    with input_tab:
        st.markdown("""
| 上传项 | 文件格式 | 几何与属性要求 |
| --- | --- | --- |
| 耕地图斑（一个文件） | Shapefile ZIP、GeoJSON / JSON | 必须为 Polygon / MultiPolygon 面；无必填属性字段，保留原属性 |
| 周边地物（可多文件） | Shapefile ZIP、GeoJSON / JSON | 支持点、线、面及其 Multi 类型；须有下表中的分类属性 |

Shapefile 打包：每套数据必须包含同名 `.shp`、`.shx`、`.dbf`、`.prj`，建议带 `.cpg` 声明中文编码。
例如 `路网.shp`、`路网.shx`、`路网.dbf`、`路网.prj`、`路网.cpg` 一起压缩为 `路网.zip`，不能只压缩 `.shp`。
ZIP 可含子目录或多套图层，程序会合并。单文件上传上限 500 MB；ZIP 解压后上限 2 GB、最多 10000 个文件。

坐标系：必须正确声明源坐标系；标准 GeoJSON 使用 WGS84 经纬度。不同文件可以使用不同坐标系，工具会统一投影。不能只改坐标系标签而不转换坐标。

分类字段不是全部必填，满足一行条件即可；按以下顺序判断同一条地物：

| 优先级 | 字段 | 有效内容示例 / 条件 | 归类 |
| --- | --- | --- | --- |
| 1 | `railway` | 有值，例如 `rail` | 铁路 |
| 2 | `highway` | 有值，例如 `tertiary`、`residential` | 公路（中文细分类见下一页） |
| 3 | `place` | 仅 `village`、`hamlet`、`town` | 村庄 |
| 4 | `landuse` | 仅 `residential` | 村庄 |

不匹配的地物会忽略，全部不匹配时停止分析。字段名兼容大小写、前后空格、`osm_` 前缀，也可读取 `tags` / `other_tags` 中的标准标签。
`railway` / `highway` 按“有值”判断，`no`、`0` 等也会被当作类型，请提前清理不适用的值。

只有 `fclass` 怎么办？目前不会直接按 `fclass`、`type` 或中文“道路类型”识别。
若是纯路网，且 `fclass` 值是 `motorway`、`primary`、`tertiary` 等 OSM 道路类型，可新增文本字段 `highway` 并复制对应值；混合图层请按地物分别填写相应分类字段。

村庄名称（可选）：按 `name:zh` → `name_zh` → `name` 优先读取，用于“紧邻XX村居民点…”；没有名称时写“村庄周边”。道路描述不显示具体路名。

耕地原字段限制：不能已有 `位置类型`、`地物子类`、`最近距离`、`位置描述`，请先重命名，避免覆盖原属性。
""")
    with class_tab:
        st.markdown("按项目约定将 `highway` 值转换为以下中文名称。连接线归入对应大类，不显示具体路名或英文类型。")
        grouped_types = {}
        for key, value in ROAD_TYPES_ZH.items():
            grouped_types.setdefault(value, []).append(key)
        st.dataframe(pd.DataFrame([
            {"道路类别": value, "对应 highway 值": "、".join(keys)}
            for value, keys in grouped_types.items()
        ]), hide_index=True, width="stretch", height=420)
        st.caption("未列出的 highway 值统一表述为“公路”。这是本项目的名称映射，不是对国道、省道或公路技术等级的法定认定。")
    with result_tab:
        st.markdown("""
几何修复：侧边栏默认开启“自动修复无效几何”。修复自相交等问题，空几何、无法修复或不符合几何类型要求的记录会跳过，不进入结果。
页面显示各文件修复及跳过数量，可下载处理明细；行号从 1 开始，多图层 ZIP 按合并顺序编号。修复可能改变形状和面积，请复核。关闭修复后会严格校验并报错。

最近地物：对整个图斑与地物计算最短距离，而不是中心点距离。相交、接触或包含时距离为 0。
以米制 UTM 投影计算；失败时尝试 WGS84 局部等距投影并提示。大范围数据建议分地区分析。距离完全相同时优先铁路，其次公路，再次村庄。

方位：使用投影坐标中“地物中心 → 图斑中心”的主方向，分东、西、南、北侧。
这是中心相对方位，不是道路行驶方向的左/右侧；长弯曲道路、交叉或重叠图斑请人工复核。中心重合时当前按东侧处理。

距离阈值：默认不启用；启用后，超过阈值的位置类型为“无”，描述为“不在公路、铁路或村庄周边”，仍保留实际最近距离。
“旁”是位置描述用语；需限定邻近范围时请启用阈值，不勾选“显示距离”也仍会计算距离并判断阈值。

| 描述选项 | 示例 |
| --- | --- |
| 都不勾选（默认） | 乡道旁 / 村道旁 / 铁路旁 / 大同村居民点旁 |
| 只显示方位 | 位于乡道东侧 |
| 只显示距离 | 乡道旁约85.20米 |
| 同时显示方位和距离 | 位于乡道东侧约85.20米 |
| 距离为 0 或不超过 0.005 米 | 不附加距离文字，保留所选的方位或“旁”表述 |

道路使用国内名称：高速公路、快速路、主干道、县道、乡道、村道、村内道路、专用道路、机耕道/生产路等，连接线归入对应大类。具体路名和英文类型不进入位置描述。

导出：GeoJSON 和 Shapefile 均为 WGS84。新增“位置类型、地物子类、最近距离、位置描述”，距离字段始终保留数值（包括 0），原始英文类别保留在“地物子类”。
Shapefile 使用 `loc_type`、`osm_sub`、`near_m`、`loc_desc` 短字段名，ZIP 内附中文字段映射；GeoJSON 保留中文列名。
DBF 文本超过 254 字节时不能导出 Shapefile，请使用 GeoJSON。

超过 5 万图斑时处理可能较慢；500 MB 上传上限不等于服务器内存容量，大数据建议拆分。
""")

with st.expander("第一步：从完整 OSM 数据提取分析材料", expanded=False):
    st.write("上传村界或分析区域面，以及完整 OSM ZIP / GeoJSON。下载的分析材料可直接放入下方“上传 OSM 地物”。")
    st.info("标准 OSM 数据包只需上传 4 类文件：`gis_osm_roads_free_1.shp`（道路）、`gis_osm_railways_free_1.shp`（铁路）、`gis_osm_places_free_1.shp`（村庄点）、`gis_osm_landuse_a_free_1.shp`（居民区面）。每类需连同同名 .shx、.dbf、.prj、.cpg 一起压缩。buildings、natural、water、traffic、transport、pofw、pois 等不需要上传。")
    st.caption("导出 ZIP 内按点、线、面分别保存 Shapefile；村庄点和居民区面均保留。可直接上传整个 ZIP 分析，无需手动合并图层。")
    st.caption("程序会根据原图层名把 fclass 自动转换为 highway、railway、place、landuse；普通建筑不会当作村庄。")

    def clear_materials():
        st.session_state.pop("materials_result", None)

    boundary_upload = st.file_uploader("村界 / 分析范围（面）", type=["zip", "geojson", "json"], key="boundary", on_change=clear_materials)
    source_uploads = st.file_uploader("完整 OSM 数据（可多文件）", type=["zip", "geojson", "json"], accept_multiple_files=True, key="full_osm", on_change=clear_materials)
    buffer_m = st.number_input("范围外扩距离（米）", min_value=0.0, max_value=100000.0, value=1000.0, step=100.0, on_change=clear_materials)
    st.caption("默认外扩 1000 米，以保留边界外的邻近道路和村庄；建议不小于分析阈值。0 表示仅提取与范围相交的地物。保留相交地物的完整形状；范围外未提取的数据不会参与后续最近邻分析。单文件最多 500 MB，超出请按图层打包上传。")
    if st.button("提取分析材料", disabled=boundary_upload is None or not source_uploads):
        clear_materials()
        try:
            with st.spinner("正在按范围读取、分类和提取 OSM 数据…"):
                area, boundary_report = extraction_area(read_vector(boundary_upload.getvalue(), boundary_upload.name), buffer_m)
                frames = [read_vector(u.getvalue(), u.name, mask=area, transform=normalize_layer) for u in source_uploads]
                extracted, counts, report = extract_materials(combine_frames(frames), area)
                classes = classify_features(extracted, reset_index=False)
                roads = extracted.loc[classes.index[classes["位置类型"].isin(["公路", "铁路"])]]
                villages = extracted.loc[classes.index[classes["位置类型"].eq("村庄")]]
                st.session_state.materials_result = (
                    export_shapefile(roads) if not roads.empty else None,
                    export_shapefile(villages) if not villages.empty else None,
                    counts, report, boundary_report,
                )
        except Exception as exc:
            st.error(f"提取失败：{exc}")
    if "materials_result" in st.session_state:
        roads_data, villages_data, counts, report, boundary_report = st.session_state.materials_result
        st.success(f"已生成 {report['输出数量']:,} 条分析地物，坐标系为 WGS84。")
        st.dataframe(counts, hide_index=True)
        st.caption(f"范围修复 {boundary_report['修复数']} 条、跳过 {boundary_report['跳过数']} 条；地物修复 {report['修复数']} 条、跳过 {report['跳过数']} 条。")
        road_col, village_col = st.columns(2)
        with road_col:
            if roads_data is not None:
                st.download_button("下载路网材料（Shapefile ZIP）", roads_data, "road_materials.zip", "application/zip")
            else:
                st.info("范围内没有匹配的公路或铁路。")
        with village_col:
            if villages_data is not None:
                st.download_button("下载村庄材料（Shapefile ZIP）", villages_data, "village_materials.zip", "application/zip")
            else:
                st.info("范围内没有匹配的村庄或居民区。")

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
            result, warnings, crs = analyze(farmland, features, threshold if enabled else None, bar.progress,
                                              show_direction=show_direction, show_distance=show_distance)
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
