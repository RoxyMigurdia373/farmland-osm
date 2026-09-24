"""GEE Sentinel-2 NDVI annual/batched CSV exporter. No imagery downloads."""
import argparse
import datetime as dt
import json
from pathlib import Path
import ee


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='已注册 Earth Engine 的 Cloud project ID')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--asset', help='GEE FeatureCollection asset ID')
    source.add_argument('--vector', help='本地 SHP / GeoJSON；将上传几何到 GEE，不下载影像')
    parser.add_argument('--id-field', default='plot_id')
    parser.add_argument('--start-year', type=int, required=True)
    parser.add_argument('--end-year', type=int, required=True)
    parser.add_argument('--interval', type=int, choices=[5, 10, 16], default=10)
    parser.add_argument('--cloud', type=float, default=60)
    parser.add_argument('--scale', type=int, default=10)
    parser.add_argument('--min-area', type=float, default=900)
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--folder', default='NDVI_exports')
    parser.add_argument('--prefix', default='ndvi_ts')
    parser.add_argument('--authenticate', action='store_true')
    parser.add_argument('--submit', action='store_true', help='提交导出任务；默认只校验并列出计划')
    args = parser.parse_args()
    if args.end_year < args.start_year or not 0 <= args.cloud <= 100 or args.batch_size < 1 or args.scale < 1 or args.min_area < 0:
        parser.error('年份、云量、批大小、像元或面积参数不合法')
    if args.authenticate:
        ee.Authenticate()
    ee.Initialize(project=args.project)
    if args.asset:
        plots = ee.FeatureCollection(args.asset)
    else:
        import geopandas as gpd
        import geemap
        frame = gpd.read_file(args.vector)
        if frame.crs is None or not frame.geom_type.isin(['Polygon', 'MultiPolygon']).all() or not frame.is_valid.all():
            raise ValueError('输入必须是正确声明 CRS 的有效面数据')
        if args.id_field not in frame or frame[args.id_field].isna().any():
            raise ValueError('缺少 ID 字段或含空 ID')
        frame[args.id_field] = frame[args.id_field].astype(str)
        if frame[args.id_field].str.strip().eq('').any() or frame[args.id_field].duplicated().any():
            raise ValueError('ID 必须非空且唯一')
        plots = geemap.geopandas_to_ee(frame[[args.id_field, frame.geometry.name]].to_crs(4326))
    total = plots.size().getInfo()
    if not total or plots.filter(ee.Filter.notNull([args.id_field])).size().getInfo() != total:
        raise ValueError('空集合或 ID 缺失')
    plots = plots.map(lambda f: f.set('plot_id', ee.String(f.get(args.id_field))))
    if plots.filter(ee.Filter.eq('plot_id', '')).size().getInfo() or plots.aggregate_count_distinct('plot_id').getInfo() != total:
        raise ValueError('ID 必须非空且唯一')
    def prepare_plot(f):
        geom = f.geometry()
        return ee.Feature(geom, {'plot_id': f.get('plot_id'), 'area_m2': geom.area(1), 'geom_type': geom.type()})
    plots = plots.map(prepare_plot)
    if plots.filter(ee.Filter.inList('geom_type', ['Polygon', 'MultiPolygon'])).size().getInfo() != total:
        raise ValueError('GEE Asset 必须全部为面')
    plots = plots.filter(ee.Filter.gte('area_m2', args.min_area)).sort('plot_id')
    count = plots.size().getInfo()
    print(f'输入 {total}，保留 {count}，面积过滤 {total-count}；批大小 {args.batch_size}')
    if not count:
        raise ValueError('面积过滤后为空')

    def ndvi(image):
        scl = image.select('SCL')
        # 排除无数据、坏像元、阴影、中高概率云、卷云、雪；保留水体及低植被。
        mask = scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        red = image.select('B4').multiply(0.0001)
        nir = image.select('B8').multiply(0.0001)
        return nir.subtract(red).divide(nir.add(red)).updateMask(mask.And(nir.add(red).neq(0))).rename('NDVI').copyProperties(image, ['system:time_start'])

    tasks = []
    for year in range(args.start_year, args.end_year + 1):
        start, end = ee.Date.fromYMD(year, 1, 1), ee.Date.fromYMD(year + 1, 1, 1)
        days = (dt.date(year+1,1,1)-dt.date(year,1,1)).days
        for batch, offset in enumerate(range(0, count, args.batch_size), 1):
            subset = ee.FeatureCollection(plots.toList(args.batch_size, offset))
            collection = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(subset.geometry()).filterDate(start, end).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', args.cloud)).map(ndvi)
            def composite(day):
                date = start.advance(day, 'day')
                stop = ee.Date(ee.Number(date.advance(args.interval, 'day').millis()).min(end.millis()))
                images = collection.filterDate(date, stop)
                empty = ee.Image.constant(0).rename('NDVI').updateMask(ee.Image.constant(0))
                image = ee.Image(ee.Algorithms.If(images.size().gt(0), images.median(), empty))
                reducer = ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True).combine(ee.Reducer.count(), sharedInputs=True)
                rows = image.reduceRegions(collection=subset, reducer=reducer, scale=args.scale, crs='EPSG:6933', tileScale=4)
                return rows.map(lambda f: ee.Feature(None, {'plot_id': f.get('plot_id'), 'date': date.format('YYYY-MM-dd'), 'NDVI': f.get('mean'), 'NDVI_std': f.get('stdDev'), 'valid_pixels': f.get('count')}))
            rows = ee.FeatureCollection(ee.List.sequence(0, days-1, args.interval).map(composite)).flatten()
            name = f'{args.prefix}_{year}_b{batch:04d}'
            task = ee.batch.Export.table.toDrive(collection=rows, description=name, folder=args.folder, fileNamePrefix=name, fileFormat='CSV', selectors=['plot_id','date','NDVI','valid_pixels','NDVI_std'])
            if args.submit:
                task.start()
            tasks.append({'name': name, 'task_id': task.id, 'submitted': args.submit})
            print(name, task.id or '计划（未提交）')
    Path('gee_tasks.json').write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
