"""按区域筛选 Geofabrik OSM 图层并标准化分类字段。"""
import geopandas as gpd
from analyzer import ROAD_TYPES_ZH, _project, repair_geometry, validate_geometry, classify_features


def extraction_area(boundary, buffer_m=1000):
    if not 0 <= buffer_m <= 100000:
        raise ValueError("缓冲距离应在 0–100000 米之间。")
    boundary, report, _ = repair_geometry(boundary, farmland=True)
    validate_geometry(boundary, farmland=True)
    crs = boundary.estimate_utm_crs()
    if crs is None:
        raise ValueError("范围无法确定米制投影，请检查坐标系。")
    metric = _project(boundary, crs)
    area = metric.geometry.union_all().buffer(buffer_m) if buffer_m else metric.geometry.union_all()
    return _project(gpd.GeoDataFrame(geometry=[area], crs=crs), 4326), report


def normalize_layer(frame, source):
    frame = frame.rename(columns={c: str(c).strip().lower() for c in frame.columns if c != frame.geometry.name}).copy()
    fc = frame.get("fclass")
    name = source.lower()
    if fc is not None:
        values = fc.fillna("").astype(str).str.lower().str.strip()
        if "roads" in name:
            field = "highway"
        elif "railways" in name:
            field = "railway"
        elif "places" in name:
            field = "place"
        elif "landuse" in name:
            field = "landuse"
        else:
            field = None
        if field:
            if field not in frame:
                frame[field] = values
            else:
                empty = frame[field].isna() | frame[field].astype(str).str.strip().eq("")
                frame.loc[empty, field] = values[empty]
        elif "gis_osm_" not in name and not any(c in frame for c in ["highway", "railway", "place", "landuse"]):
            # 仅识别含义明确的值，不将建筑或其他地物猜成居民区。
            frame["highway"] = values.where(values.isin(ROAD_TYPES_ZH), None)
            frame["place"] = values.where(values.isin(["village", "hamlet", "town"]), None)
    columns = [c for c in ["osm_id", "name", "name:zh", "name_zh", "highway", "railway", "place", "landuse"] if c in frame]
    return frame[columns + [frame.geometry.name]]


def extract_materials(frame, area):
    original = len(frame)
    frame, repair_report, _ = repair_geometry(frame)
    if frame.empty:
        raise ValueError("范围内没有可用几何。")
    frame = _project(frame, 4326)
    selected = frame.geometry.intersects(area.geometry.iloc[0])
    frame = frame.loc[selected].reset_index(drop=True)
    # 保留完整地物，避免裁剪改变最近距离和用于方位判断的中心位置。
    classified = classify_features(frame, reset_index=False)
    result = frame.loc[classified.index].reset_index(drop=True)
    if result.empty:
        raise ValueError("范围内未识别到道路、铁路或村庄。请检查图层名称和分类字段。")
    return result, classified["位置类型"].value_counts().rename_axis("类别").reset_index(name="数量"), {
        "读取数量": original, **repair_report, "输出数量": len(result)
    }
