"""上传读取和离线导出；临时文件仅存在于当前服务器并自动清理。"""
import io
import json
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

import geopandas as gpd
import pandas as pd

FIELD_MAP = {"位置类型": "loc_type", "地物子类": "osm_sub", "最近距离": "near_m", "位置描述": "loc_desc"}
FIELD_MAP.update({"中心经度": "center_lon", "中心纬度": "center_lat"})
for radius in (200, 500):
    for field, short in [("位置类型", "type"), ("地物子类", "sub"), ("最近距离", "dist"), ("位置描述", "desc")]:
        FIELD_MAP[f"{radius}米{field}"] = f"r{radius}_{short}"
MAX_EXTRACTED = 2 * 1024**3


def read_vector(data, filename, mask=None, transform=None):
    suffix = Path(filename).suffix.lower()
    try:
        with tempfile.TemporaryDirectory(prefix="farmland_read_") as directory:
            root = Path(directory)
            if suffix in {".geojson", ".json"}:
                source = root / "input.geojson"
                source.write_bytes(data)
                frame = gpd.read_file(source, engine="fiona", mask=mask)
                if transform:
                    frame = transform(frame, filename)
            elif suffix == ".zip":
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = archive.infolist()
                    if len(members) > 10000 or sum(m.file_size for m in members) > MAX_EXTRACTED:
                        raise ValueError("压缩包解压后超过 2 GB 或文件数量过多，请拆分数据。")
                    seen = set()
                    for member in members:
                        name = PurePosixPath(member.filename.replace("\\", "/"))
                        if name.is_absolute() or ".." in name.parts or any(":" in p for p in name.parts):
                            raise ValueError("压缩包包含不安全路径。")
                        normalized = str(name).lower()
                        if normalized in seen:
                            raise ValueError("压缩包存在重复文件名。")
                        seen.add(normalized)
                        if member.is_dir():
                            continue
                        # 只提取矢量相关文件，不解压符号链接或其他内容。
                        if name.suffix.lower() not in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
                            continue
                        destination = root.joinpath(*name.parts).with_suffix(name.suffix.lower())
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as src, destination.open("wb") as dst:
                            import shutil
                            shutil.copyfileobj(src, dst)
                shapes = list(root.rglob("*.shp"))
                if not shapes:
                    raise ValueError("压缩包中没有 Shapefile（.shp）。")
                frames = []
                for source in shapes:
                    missing = [ext for ext in (".shx", ".dbf", ".prj") if not source.with_suffix(ext).exists()]
                    if missing:
                        raise ValueError(f"{source.name} 缺少必要配套文件：{', '.join(missing)}")
                    layer = gpd.read_file(source, engine="fiona", mask=mask)
                    if transform:
                        layer = transform(layer, source.name)
                    frames.append(layer)
                frame = combine_frames(frames)
            else:
                raise ValueError("仅支持 Shapefile ZIP、GeoJSON 或 JSON 文件。")
            if frame.crs is None:
                raise ValueError("文件未定义坐标系，请补充正确坐标系后重试。")
            return frame
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"无法读取“{filename}”，请检查文件是否完整、格式是否正确。详细信息：{exc}") from exc


def combine_frames(frames):
    if not frames:
        raise ValueError("没有可合并的矢量数据。")
    if any(frame.crs is None for frame in frames):
        raise ValueError("数据缺少坐标系，无法合并。")
    target = frames[0].crs
    normalized = []
    for frame in frames:
        frame = frame.to_crs(target)
        if frame.geometry.name != "geometry":
            frame = frame.rename_geometry("geometry")
        normalized.append(frame)
    return gpd.GeoDataFrame(pd.concat(normalized, ignore_index=True), geometry="geometry", crs=target)


def export_geojson(frame):
    return frame.to_crs(4326).to_json(ensure_ascii=False, na="null", drop_id=True).encode("utf-8")


def export_shapefile(frame):
    output = frame.to_crs(4326).copy()
    mapping, used = {}, set(FIELD_MAP.values())
    for i, column in enumerate(output.columns):
        if column == output.geometry.name:
            continue
        if column in FIELD_MAP:
            mapping[column] = FIELD_MAP[column]
        else:
            # DBF 限制为 10 字节；对所有不安全/冲突字段使用确定性短名。
            name = str(column)
            if not name.isascii() or len(name) > 10 or not name.isidentifier() or name.lower() in used:
                counter = i
                name = f"f{counter:08d}"
                while name.lower() in used:
                    counter += 1
                    name = f"f{counter:08d}"
            mapping[column] = name
            used.add(name.lower())
        if output[column].dtype == "object":
            output[column] = output[column].map(
                lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            )
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].astype(str)
        # 拒绝静默截断中文/长文本；完整属性仍可通过 GeoJSON 下载。
        if output[column].map(lambda v: isinstance(v, str) and len(v.encode("utf-8")) > 254).any():
            raise ValueError(f"字段“{column}”含超过 DBF 254 字节限制的文本，请使用 GeoJSON 或先缩短文本。")
    output = output.rename(columns=mapping)
    with tempfile.TemporaryDirectory(prefix="farmland_export_") as directory:
        root = Path(directory)
        families = {
            "points": ["Point"], "multipoints": ["MultiPoint"],
            "lines": ["LineString", "MultiLineString"],
            "polygons": ["Polygon", "MultiPolygon"],
        }
        if output.empty or not output.geom_type.isin(sum(families.values(), [])).all():
            raise ValueError("导出数据为空或包含不支持的几何类型，请先修复数据。")
        layers = [(name, output.loc[output.geom_type.isin(types)]) for name, types in families.items()]
        layers = [(name, layer) for name, layer in layers if not layer.empty]
        for name, layer in layers:
            stem = "result" if len(layers) == 1 else f"result_{name}"
            layer.to_file(root / f"{stem}.shp", driver="ESRI Shapefile", encoding="UTF-8", engine="fiona", index=False)
            (root / f"{stem}.cpg").write_text("UTF-8", encoding="ascii")
        (root / "字段映射.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.iterdir()):
                archive.write(path, path.name)
        return buffer.getvalue()
