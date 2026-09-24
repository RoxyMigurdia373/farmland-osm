// 耕地 NDVI 工作台：直接粘贴到 https://code.earthengine.google.com/
// 1. 把村内耕地图斑上传为 GEE Table Asset，替换下面一行。
//    若 Imports 中已导入为 table，可将下面一行改为 var plots = table;
var plots = ee.FeatureCollection('projects/YOUR_PROJECT/assets/YOUR_PLOTS');

// 2. 设置分析年份（含首尾年份）。其他参数通常不用改。
var START_YEAR = 2023;
var END_YEAR = 2024;

// 自动ID：优先使用完整、唯一、非空的 plot_id；否则使用 Asset system:index。
// 不按面积删除小图斑。像元太少时在CSV中保留质量字段，供复核。
var INTERVAL_DAYS = 10;
var CLOUD_PERCENT = 60;
var BATCH_SIZE = 1000;
var DRIVE_FOLDER = 'NDVI_exports';
var EXPORT_PREFIX = 'ndvi_ts';

if (START_YEAR < 2017 || END_YEAR < START_YEAR || END_YEAR > new Date().getFullYear()) {
  throw new Error('请检查年份：Sentinel-2 SR 从2017年起可用，结束年份不能早于开始年份或晚于当前年份。');
}

function addNDVI(image) {
  var scl = image.select('SCL');
  var clear = scl.neq(0).and(scl.neq(1)).and(scl.neq(3))
    .and(scl.neq(8)).and(scl.neq(9)).and(scl.neq(10)).and(scl.neq(11));
  var red = image.select('B4').multiply(0.0001);
  var nir = image.select('B8').multiply(0.0001);
  return nir.subtract(red).divide(nir.add(red))
    .updateMask(clear.and(nir.add(red).neq(0)))
    .rename('NDVI').copyProperties(image, ['system:time_start']);
}

// 只请求汇总校验信息，不把全量地块下载到浏览器。
var checked = plots.map(function(f) {
  var value = f.get('plot_id');
  var id = ee.String(ee.Algorithms.If(ee.Algorithms.IsEqual(value, null), '', value));
  return f.set('_input_id', id, '_geom_type', f.geometry().type());
});
ee.Dictionary({
  count: checked.size(),
  validIds: checked.filter(ee.Filter.neq('_input_id', '')).size(),
  uniqueIds: checked.aggregate_count_distinct('_input_id'),
  polygons: checked.filter(ee.Filter.inList('_geom_type', ['Polygon', 'MultiPolygon'])).size(),
  indexCount: checked.filter(ee.Filter.notNull(['system:index'])).size(),
  uniqueIndices: checked.aggregate_count_distinct('system:index')
}).evaluate(function(info, error) {
  if (error) { print('读取矢量失败，请检查 Asset 路径与权限：', error); return; }
  if (!info.count) { print('矢量为空，请更换输入。'); return; }
  if (info.polygons !== info.count) { print('输入包含非面几何，请上传耕地面图斑。'); return; }
  var useInputId = info.validIds === info.count && info.uniqueIds === info.count;
  if (!useInputId && (info.indexCount !== info.count || info.uniqueIndices !== info.count)) {
    print('plot_id 和 system:index 均不能唯一标识图斑，请为源矢量添加唯一 plot_id。'); return;
  }
  var ready = checked.map(function(f) {
    return ee.Feature(f.geometry(), {
      plot_id: useInputId ? f.get('_input_id') : ee.String('plot_').cat(ee.String(f.get('system:index'))),
      source_index: f.get('system:index')
    });
  }).sort('plot_id');
  print('图斑数：', info.count, 'ID方式：', useInputId ? '保留plot_id' : '自动：plot_ + system:index');
  print('ID在本次所有年份和批次一致；如重新上传Asset，自动ID可能变化。');

  // ID对应表保留原矢量属性，用于关联原地块；无需导入工作台。
  var mapping = checked.map(function(f) {
    var properties = f.toDictionary().remove(['_input_id', '_geom_type']);
    return ee.Feature(null, properties).set({
      plot_id: useInputId ? f.get('_input_id') : ee.String('plot_').cat(ee.String(f.get('system:index'))),
      source_index: f.get('system:index')
    });
  });
  Export.table.toDrive({collection: mapping, description: EXPORT_PREFIX + '_id_mapping',
    folder: DRIVE_FOLDER, fileNamePrefix: EXPORT_PREFIX + '_id_mapping', fileFormat: 'CSV'});

  function createTask(year, offset, batch) {
    var subset = ee.FeatureCollection(ready.toList(BATCH_SIZE, offset));
    var start = ee.Date.fromYMD(year, 1, 1);
    var end = ee.Date.fromYMD(year + 1, 1, 1);
    var images = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
      .filterBounds(subset.geometry()).filterDate(start, end)
      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', CLOUD_PERCENT)).map(addNDVI);
    var rows = ee.FeatureCollection(ee.List.sequence(0, end.difference(start, 'day').subtract(1), INTERVAL_DAYS)
      .map(function(day) {
        var date = start.advance(day, 'day');
        var stop = ee.Date(date.advance(INTERVAL_DAYS, 'day').millis().min(end.millis()));
        var window = images.filterDate(date, stop);
        // 空时段也保留行，NDVI为空，不填0，以免错误判为裸地。
        var empty = ee.Image.constant(0).rename('NDVI').updateMask(ee.Image.constant(0));
        var composite = ee.Image(ee.Algorithms.If(window.size().gt(0), window.median(), empty));
        var reducer = ee.Reducer.mean().combine({reducer2: ee.Reducer.stdDev(), sharedInputs: true})
          .combine({reducer2: ee.Reducer.count(), sharedInputs: true});
        return composite.reduceRegions({collection: subset, reducer: reducer,
          scale: 10, crs: 'EPSG:6933', tileScale: 4}).map(function(f) {
            return ee.Feature(null, {plot_id: f.get('plot_id'), date: date.format('YYYY-MM-dd'),
              NDVI: f.get('mean'), valid_pixels: f.get('count'), NDVI_std: f.get('stdDev')});
          });
      })).flatten();
    var name = EXPORT_PREFIX + '_' + year + '_b' + ('0000' + batch).slice(-4);
    Export.table.toDrive({collection: rows, description: name, folder: DRIVE_FOLDER,
      fileNamePrefix: name, fileFormat: 'CSV',
      selectors: ['plot_id', 'date', 'NDVI', 'valid_pixels', 'NDVI_std']});
  }
  for (var year = START_YEAR; year <= END_YEAR; year++) {
    for (var offset = 0, batch = 1; offset < info.count; offset += BATCH_SIZE, batch++) {
      createTask(year, offset, batch);
    }
  }
  print('导出任务已生成：请在右侧 Tasks 点击 Run。完成后从Drive下载 ndvi_ts_年份_b批次.csv。');
  print('工作台可同时选择全部年度/批次CSV，自动合并，无需改字段或合并文件。不要选择 id_mapping.csv。');
});
