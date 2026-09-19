"""离线空间分类与最近距离分析；距离为图斑边界/内部到地物的最短距离。"""
import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.strtree import STRtree
from shapely import make_valid, get_coordinates
from shapely.ops import unary_union

OUTPUT_FIELDS = ["位置类型", "地物子类", "最近距离", "位置描述"]
PRIORITY = {"铁路": 0, "公路": 1, "村庄": 2}
ROAD_TYPES_ZH = {
    "motorway": "高速公路", "motorway_link": "高速公路",
    "trunk": "干线公路", "trunk_link": "干线公路",
    "primary": "主要公路", "primary_link": "主要公路",
    "secondary": "次要公路", "secondary_link": "次要公路",
    "tertiary": "一般公路", "tertiary_link": "一般公路",
    "unclassified": "未分级公路", "residential": "居民区道路",
    "service": "服务道路", "living_street": "生活街道",
    "road": "类别未明确的道路", "busway": "公交专用道路",
    "bus_guideway": "导向公交专用道路",
}
ROAD_TYPES_ZH.update(dict.fromkeys({"track", "track_grade1", "track_grade2", "track_grade3", "track_grade4", "track_grade5"}, "农林道路"))
ROAD_TYPES_ZH.update(dict.fromkeys({"footway", "path", "steps", "pedestrian"}, "步行道路"))
ROAD_TYPES_ZH.update({"cycleway": "自行车道", "bridleway": "马道", "construction": "在建道路", "proposed": "规划道路"})


def _value(value):
    if value is None or (not isinstance(value, (dict, list)) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "null", "none", "nan"} else text


def classify_features(frame):
    """标准字段优先，同时兼容大小写、osm_ 前缀、tags 和 other_tags。"""
    types, subtypes, names = [], [], []
    for row in frame.drop(columns=frame.geometry.name).to_dict("records"):
        tags = {}
        for key, value in row.items():
            name = str(key).strip().lower()
            if name in {"tags", "other_tags"}:
                if isinstance(value, dict):
                    tags.update({str(k).lower(): _value(v) for k, v in value.items()})
                elif isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, dict):
                            tags.update({str(k).lower(): _value(v) for k, v in parsed.items()})
                    except ValueError:
                        tags.update(re.findall(r'"([^"]+)"\s*=>\s*"([^"]*)"', value))
        for key, value in row.items():
            name = str(key).strip().lower().removeprefix("osm_")
            if name in {"railway", "highway", "place", "landuse", "name", "name:zh", "name_zh"} and _value(value):
                tags[name] = _value(value)
        if tags.get("railway"):
            kind, subtype = "铁路", tags["railway"]
        elif tags.get("highway"):
            kind, subtype = "公路", tags["highway"]
        elif tags.get("place", "").lower() in {"village", "hamlet", "town"}:
            kind, subtype = "村庄", tags["place"]
        elif tags.get("landuse", "").lower() == "residential":
            kind, subtype = "村庄", "residential"
        else:
            kind, subtype = "", ""
        types.append(kind)
        subtypes.append(subtype)
        names.append(tags.get("name:zh") or tags.get("name_zh") or tags.get("name") or "")
    result = frame[[frame.geometry.name]].copy()
    result["位置类型"], result["地物子类"] = types, subtypes
    result["地物名称"] = names
    return result.loc[result["位置类型"] != ""].reset_index(drop=True)


def repair_geometry(frame, farmland=False):
    """保留行属性及顺序，面修复后只保留面部分，不虚构空几何。"""
    if frame.crs is None:
        raise ValueError("缺少坐标系信息，自动修复不能补充坐标系。")
    allowed = {"Polygon", "MultiPolygon"} if farmland else {
        "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"
    }
    positions, geometries, issues = [], [], []
    repaired = 0

    def polygons(geometry):
        if geometry.geom_type == "Polygon":
            return [geometry]
        return [p for part in getattr(geometry, "geoms", []) for p in polygons(part)]

    for position, geometry in enumerate(frame.geometry):
        reason, changed = "", False
        if geometry is None or geometry.is_empty:
            reason = "空几何，无法恢复坐标"
        elif not np.isfinite(get_coordinates(geometry)).all():
            reason = "坐标含非有限值，无法可靠修复"
        else:
            try:
                if not geometry.is_valid:
                    geometry = make_valid(geometry)
                    changed = True
                if farmland and geometry.geom_type in {"GeometryCollection", "MultiPolygon"}:
                    geometry = unary_union(polygons(geometry))
                    changed = True
                if geometry.is_empty or geometry.geom_type not in allowed or not geometry.is_valid:
                    reason = "修复后无可用面几何" if farmland else "修复后几何为空、无效或类型不支持"
            except Exception:
                reason = "几何修复失败"
        if reason:
            issues.append({"原始行号": position + 1, "处理": "跳过", "说明": reason})
            continue
        if changed:
            repaired += 1
            issues.append({"原始行号": position + 1, "处理": "已修复", "说明": "已修复拓扑或提取面部分，请复核形状"})
        positions.append(position)
        geometries.append(geometry)
    output = frame.iloc[positions].copy()
    output.geometry = gpd.GeoSeries(geometries, index=output.index, crs=frame.crs)
    return output.reset_index(drop=True), {
        "输入数": len(frame), "修复数": repaired, "跳过数": len(frame) - len(output), "保留数": len(output)
    }, issues


def validate_geometry(frame, farmland=False):
    if frame.empty:
        raise ValueError("矢量文件中没有地物。")
    if frame.crs is None:
        raise ValueError("缺少坐标系信息，请补充正确的 .prj 或 GeoJSON CRS 后重试。")
    bad = frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid
    if bad.any():
        raise ValueError(f"发现 {int(bad.sum())} 个空或无效几何，请勾选侧边栏“自动修复无效几何”后重试，或在 GIS 软件中修复。")
    allowed = {"Polygon", "MultiPolygon"} if farmland else {
        "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"
    }
    if not frame.geom_type.isin(allowed).all():
        raise ValueError("耕地图斑必须全部为 Polygon / MultiPolygon。" if farmland else "OSM 数据包含不支持的几何类型。")
    if not np.isfinite(frame.total_bounds).all():
        raise ValueError("几何坐标存在非有限值。")


def _project(frame, crs):
    projected = frame.to_crs(crs)
    if not np.isfinite(projected.total_bounds).all() or not projected.geometry.is_valid.all():
        raise ValueError("坐标投影产生无效坐标。")
    return projected


def analyze(farmland, features, threshold=None, progress=None, chunk_size=5000):
    validate_geometry(farmland, farmland=True)
    validate_geometry(features)
    if threshold is not None and (not np.isfinite(threshold) or threshold < 0):
        raise ValueError("最大距离阈值必须为非负有限数值。")
    if chunk_size < 1:
        raise ValueError("分块大小必须大于零。")
    collisions = set(OUTPUT_FIELDS).intersection(farmland.columns)
    if collisions:
        raise ValueError(f"输入已含输出字段：{'、'.join(sorted(collisions))}，请先重命名以免覆盖原属性。")
    warnings = []
    try:
        result = _project(farmland, 4326).reset_index(drop=True)
    except Exception as exc:
        raise ValueError("无法转换到 WGS84，请检查源坐标系定义。") from exc
    west, south, east, north = result.total_bounds
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError("WGS84 坐标超出经纬度范围，请检查源坐标系。")
    if east - west > 6 or north - south > 8:
        warnings.append("数据跨度较大，单一局部投影可能存在明显距离偏差，建议按地区分批分析。")
    try:
        metric_crs = result.estimate_utm_crs()
        if metric_crs is None:
            raise ValueError("无法确定 UTM 带")
        land_m, osm_m = _project(result, metric_crs), _project(features, metric_crs)
    except Exception:
        # WGS84 经纬度不是米；回退到基于 WGS84 的局部等距投影。
        try:
            metric_crs = CRS.from_proj4(
                f"+proj=aeqd +lat_0={(south+north)/2} +lon_0={(west+east)/2} +datum=WGS84 +units=m"
            )
            land_m, osm_m = _project(result, metric_crs), _project(features, metric_crs)
        except Exception as exc:
            raise ValueError("UTM 和 WGS84 局部近似投影均失败，请检查数据坐标系及范围。") from exc
        warnings.append("UTM 投影失败，已回退到基于 WGS84 的局部等距投影；距离为近似值，可能存在偏差。")
    tree = STRtree(osm_m.geometry.to_numpy())
    records = []
    for start in range(0, len(land_m), chunk_size):
        geometries = land_m.geometry.iloc[start:start + chunk_size].to_numpy()
        pairs, distances = tree.query_nearest(geometries, return_distance=True, all_matches=True)
        # 同距离按铁路、公路、村庄排序，然后按输入顺序稳定选择。
        candidates = pd.DataFrame({"parcel": pairs[0], "feature": pairs[1], "distance": distances})
        candidates["priority"] = osm_m["位置类型"].iloc[pairs[1]].map(PRIORITY).to_numpy()
        chosen = candidates.sort_values(["parcel", "distance", "priority", "feature"]).drop_duplicates("parcel")
        for item in chosen.itertuples():
            feature = osm_m.iloc[item.feature]
            kind, subtype = feature["位置类型"], feature["地物子类"]
            distance = float(item.distance)
            if threshold is not None and distance > threshold:
                kind, subtype, description = "无", "", "不在公路、铁路或村庄周边"
            else:
                relation = "周边" if kind == "村庄" else "边"
                label = kind
                if kind == "公路":
                    label = ROAD_TYPES_ZH.get(str(subtype).strip().lower(), "类别未明确的道路")
                description = f"位于{label}{relation}，最近距离约 {distance:.2f} 米"
            records.append((kind, subtype, round(distance, 2), description))
        if progress:
            progress(min(start + chunk_size, len(land_m)) / len(land_m))
    result[OUTPUT_FIELDS] = pd.DataFrame(records, columns=OUTPUT_FIELDS, index=result.index)
    return result, warnings, metric_crs.to_string()


def summarize(result):
    return result.groupby("位置类型", sort=False).agg(
        地块数=("位置类型", "size"), 平均距离_米=("最近距离", "mean")
    ).round(2).reset_index()
