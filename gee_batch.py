"""Bounded batch exports. No tokens or geometry are persisted on disk."""
import contextlib
import datetime
import hashlib
import json

from gee_online import LOCK

MAX_PLOTS = 150_000
PENDING_LIMIT = 20  # Conservative app guard, not a claim about the project's quota.
ACTIVE = {'READY', 'RUNNING', 'CANCEL_REQUESTED'}


def analysis_window(year, end_exclusive=None, today=None):
    """Freeze the available period; never request future observations."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    start = datetime.date(int(year), 1, 1)
    annual_end = datetime.date(int(year)+1, 1, 1)
    end = datetime.date.fromisoformat(end_exclusive) if end_exclusive else min(annual_end, today)
    if year < 2017 or not start < end <= min(annual_end, today):
        raise ValueError('分析时间范围无效，不能分析未来日期。')
    return start, end, end < annual_end


@contextlib.contextmanager
def connection(project, token):
    import ee
    from google.oauth2.credentials import Credentials
    if not LOCK.acquire(blocking=False):
        raise ValueError('另一个GEE请求正在处理，请稍后重试。')
    try:
        ee.Initialize(credentials=Credentials(token=token), project=project)
        ee.data.setDeadline(120000)
        yield ee
    finally:
        try:
            ee.Reset()
        finally:
            LOCK.release()


def ranges(count, batch_size):
    if not 1 <= count <= MAX_PLOTS:
        raise ValueError('批量试运行支持1至150000个图斑。')
    if not 100 <= batch_size <= 2000:
        raise ValueError('每批图斑数应在100至2000之间。')
    return [(i, min(batch_size, count-i)) for i in range(0, count, batch_size)]


def polygon_assets(ee, plots):
    return plots.map(lambda f: f.set('_geometry_type_check', f.geometry().type())).filter(
        ee.Filter.inList('_geometry_type_check', ['Polygon', 'MultiPolygon']))


def collection_polygons(ee, plots):
    """Recover polygon components only; never buffer collapsed points/lines."""
    collections = plots.map(lambda f: f.set('_geometry_type_check', f.geometry().type())).filter(
        ee.Filter.eq('_geometry_type_check', 'GeometryCollection'))
    def parts(f):
        components = ee.FeatureCollection(f.geometry().geometries().map(
            lambda g: ee.Feature(ee.Geometry(g)).set('_type', ee.Geometry(g).type())))
        polygons = components.filter(ee.Filter.inList('_type', ['Polygon', 'MultiPolygon']))
        return f.set('_parts', polygons.toList(polygons.size())).set('_part_count', polygons.size())
    candidates = collections.map(parts).filter(ee.Filter.gt('_part_count', 0))
    return candidates.map(lambda f: ee.Feature(ee.FeatureCollection(ee.List(f.get('_parts'))).geometry(),
        f.toDictionary(f.propertyNames().removeAll(['_parts', '_part_count', '_geometry_type_check']))))


def selected_assets(ee, plots, recover=False):
    return collection_polygons(ee, plots) if recover else polygon_assets(ee, plots)


def inspect_asset(project, token, asset, id_field, year, batch_size, recover=False):
    _, cutoff, provisional = analysis_window(year)
    if not asset.strip() or not id_field.strip():
        raise ValueError('请填写GEE表格资产路径和唯一ID字段。')
    with connection(project, token) as ee:
        plots = ee.FeatureCollection(asset)
        source_count = plots.size().getInfo()
        ranges(source_count, batch_size)
        geometry_types = plots.map(lambda f: f.set('_geometry_type_check', f.geometry().type())).aggregate_histogram('_geometry_type_check').getInfo()
        plots = selected_assets(ee, plots, recover)
        count = plots.size().getInfo()
        plan = ranges(count, batch_size)
        valid = plots.filter(ee.Filter.notNull([id_field])).filter(ee.Filter.neq(id_field, '')).size().getInfo()
        distinct = plots.aggregate_count_distinct(id_field).getInfo()
        if valid != count or distinct != count:
            raise ValueError('所选ID字段存在空值或重复值，请选择唯一且非空的ID字段。')
    spec = dict(project=project, asset=asset, id_field=id_field, year=int(year), batch_size=int(batch_size), count=count,
                source_count=source_count, excluded_count=source_count-count, geometry_types=geometry_types, algorithm='ndvi-v2-time-preserved')
    # Keep completed-year plan IDs stable so existing exports are not repeated.
    if provisional:
        spec.update(end_exclusive=cutoff.isoformat(), provisional=True)
    if recover:
        spec['recover_collections'] = True
    spec['job_id'] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
    spec['batches'] = [{'index': i, 'offset': offset, 'count': size,
                        'description': f"ndvi_{spec['job_id']}_{i:05d}"}
                       for i, (offset, size) in enumerate(plan)]
    return spec


def annual_table(ee, plots, year, id_field, end_exclusive=None):
    first, cutoff, _ = analysis_window(year, end_exclusive)
    start, end = ee.Date(first.isoformat()), ee.Date(cutoff.isoformat())
    def ndvi(image):
        scl = image.select('SCL')
        mask = scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        nir, red = image.select('B8').multiply(.0001), image.select('B4').multiply(.0001)
        return nir.subtract(red).divide(nir.add(red)).updateMask(mask.And(nir.add(red).neq(0))).rename('NDVI').copyProperties(image, ['system:time_start'])
    images = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(plots.geometry()).filterDate(start, end).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 60)).map(ndvi)
    days = (cutoff-first).days
    def period(day):
        date = start.advance(day, 'day')
        subset = images.filterDate(date, ee.Date(date.advance(10, 'day').millis().min(end.millis())))
        blank = ee.Image.constant(0).rename('NDVI').updateMask(ee.Image.constant(0))
        composite = ee.Image(ee.Algorithms.If(subset.size().gt(0), subset.median(), blank))
        reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
        output = composite.reduceRegions(collection=plots, reducer=reducer, scale=10, crs='EPSG:4326', tileScale=4)
        return output.map(lambda f: ee.Feature(None, {'plot_id': f.get(id_field), 'date': date.format('YYYY-MM-dd'), 'NDVI': f.get('mean'), 'valid_pixels': f.get('count')}))
    return ee.FeatureCollection(ee.List.sequence(0, days-1, 10).map(period)).flatten()


def task_index(tasks):
    result = {}
    rank = {'COMPLETED': 4, 'RUNNING': 3, 'READY': 3, 'CANCEL_REQUESTED': 3}
    for task in tasks:
        name = task.get('description', '')
        if name not in result or rank.get(task.get('state'), 0) > rank.get(result[name].get('state'), 0):
            result[name] = task
    return result


def select_batches(spec, tasks, limit, retry=False):
    lookup = task_index(tasks)
    slots = max(0, PENDING_LIMIT-sum(t.get('state') in ACTIVE for t in tasks))
    selected = []
    for batch in spec['batches']:
        old = lookup.get(batch['description'])
        if old is None or (retry and old.get('state') in {'FAILED', 'CANCELLED'}):
            selected.append(batch)
    return selected[:min(slots, max(0, min(int(limit), 10)))]


def status(spec, token):
    with connection(spec['project'], token) as ee:
        tasks = ee.data.getTaskList()
    lookup = task_index(tasks)
    return [{**b, 'state': lookup.get(b['description'], {}).get('state', 'NOT_SUBMITTED'),
             'task_id': lookup.get(b['description'], {}).get('id', ''),
             'error': lookup.get(b['description'], {}).get('error_message', '')}
            for b in spec['batches']]


def submit(spec, token, limit=5, retry=False):
    submitted = []
    with connection(spec['project'], token) as ee:
        tasks = ee.data.getTaskList()
        batches = select_batches(spec, tasks, limit, retry)
        plots = selected_assets(ee, ee.FeatureCollection(spec['asset']), spec.get('recover_collections', False)).sort(spec['id_field'])
        if plots.size().getInfo() != spec['count']:
            raise ValueError('资产图斑数量已改变，请重新检查并生成计划。')
        for batch in batches:
            try:
                chunk = ee.FeatureCollection(plots.toList(batch['count'], batch['offset']))
                task = ee.batch.Export.table.toDrive(
                    collection=annual_table(ee, chunk, spec['year'], spec['id_field'], spec.get('end_exclusive')),
                    description=batch['description'], folder=f"ndvi_{spec['job_id']}",
                    fileNamePrefix=batch['description'], fileFormat='CSV',
                    selectors=['plot_id', 'date', 'NDVI', 'valid_pixels'])
                task.start()
                submitted.append({'description': batch['description'], 'task_id': task.id})
            except Exception:
                # Earlier tasks may already be running: never silently discard partial success.
                return submitted, '后续批次提交失败或响应不确定，请先刷新任务状态再重试；已提交任务继续运行。'
    return submitted, ''


def render(token):
    import streamlit as st
    st.subheader('大批量试运行 · 最多15万图斑')
    st.info('大批量请先将SHP上传为GEE表格资产，再在这里选择资产。现有100图斑直接上传入口仍可使用。任务由GEE后台执行，结果分批写入当前Google账号的Drive。')
    st.caption('此入口不在Streamlit内存中加载15万几何。默认每批1000块，每次提交5批；最多保留20个当前账号可见的待处理任务。这是保守保护值，不代表已核实的项目配额。实际并发由GEE调度。')
    project = st.text_input('批量任务项目ID', value='sa-2-496905')
    asset = st.text_input('GEE表格资产路径', placeholder='projects/项目ID/assets/耕地图斑')
    id_field = st.text_input('唯一ID字段', value='system:index')
    year = st.number_input('批量分析年份', 2017, datetime.date.today().year, datetime.date.today().year-1)
    if year == datetime.date.today().year:
        st.warning('当年仅分析截至当前UTC日期之前的可用影像，结果为阶段性筛查，不能据此确认全年未种植或撂荒。')
    size = st.number_input('每批图斑数', 100, 2000, 1000, 100)
    recover = st.checkbox('仅恢复几何集合中的面（补充批次）')
    if recover:
        st.caption('单独提取GeometryCollection内的面，生成补充任务；不重复纯面批次，不把点线缓冲成耕地。最终几何仍使用原始县级矢量。')
    if project.strip() == 'sa-2-496905':
        st.caption('配额核查快照（2026-09-24）：非商业月额度540000 EECU秒，当时已用7662；用量会变化，请以Google控制台为准。图斑数不能直接换算为EECU。先试跑少量批次。')
    st.caption('提交期间请保持资产内容不变。ID必须非空且唯一；分批依据ID排序。15万块一年约555万行，结果请逐批分析，不要全部加载到浏览器。')
    if st.button('检查资产并生成批次计划'):
        try:
            with st.spinner('检查资产数量与唯一ID…'):
                st.session_state.gee_batch_spec = inspect_asset(project.strip(), token, asset.strip(), id_field.strip(), year, size, recover)
            st.session_state.pop('gee_batch_status', None)
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error('资产检查失败：请检查资产路径、读取权限、项目注册和授权有效期。')
    spec = st.session_state.get('gee_batch_spec')
    if not spec:
        return
    if spec.get('algorithm') != 'ndvi-v2-time-preserved':
        st.warning('算法版本已更新，请重新检查资产生成计划。旧版结果不要用于分析。')
        return
    if spec.get('recover_collections'):
        st.info(f"补充计划：从几何集合中恢复{spec['count']}条面，纯面批次另行处理。")
    elif spec.get('excluded_count', 0):
        st.warning(f"原资产{spec['source_count']}条，排除非纯面{spec['excluded_count']}条（点、线、几何集合），本次仅分析{spec['count']}条面。原资产未修改。类型统计：{spec['geometry_types']}")
    current = (project.strip(), asset.strip(), id_field.strip(), int(year), int(size))
    expected = (spec['project'], spec['asset'], spec['id_field'], spec['year'], spec['batch_size'])
    if current != expected or recover != spec.get('recover_collections', False):
        st.warning('参数已修改，请重新检查资产生成计划后提交。')
        return
    st.write(f"计划：{spec['count']:,} 个图斑，{len(spec['batches'])} 批，年份 {spec['year']}。Drive文件夹：ndvi_{spec['job_id']}")
    if spec.get('provisional'):
        st.caption(f"年度未完整；固定截止日期（不含）：{spec['end_exclusive']}。实际有效观测以CSV非空记录为准。")
    st.download_button('下载批次计划JSON', json.dumps(spec, ensure_ascii=False, indent=2), f"ndvi_{spec['job_id']}_plan.json", 'application/json')
    accepted = st.checkbox('同意由GEE后台计算该资产，并将分批结果导出到我的Google Drive')
    limit = st.number_input('本次提交批次数', 1, 10, 5)
    retry = st.checkbox('重试已失败或已取消的批次')
    st.caption('先提交少量批次检查结果。网页关闭后，已提交任务继续；未提交批次不会自动补交。重新登录、输入相同参数生成计划后，可刷新状态并继续提交。GEE历史任务记录有保留期限，长期任务请另存状态表，避免重复导出。')
    if st.button('提交下一组批次', disabled=not accepted):
        try:
            with st.spinner('正在提交，完成后可关闭页面…'):
                sent, warning = submit(spec, token, limit, retry)
            st.success(f'本次已提交 {len(sent)} 批。')
            if warning:
                st.warning(warning)
            if not sent and not warning:
                st.info('没有可提交批次，或待处理任务已达到保护上限。请刷新状态。')
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error('无法读取GEE任务队列，请检查授权、项目权限或稍后重试。')
    if st.button('刷新批次状态'):
        try:
            st.session_state.gee_batch_status = status(spec, token)
        except Exception:
            st.error('任务状态读取失败，请检查授权或稍后重试。')
    rows = st.session_state.get('gee_batch_status')
    if rows:
        import pandas as pd
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.download_button('下载任务状态CSV', pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'), 'ndvi_tasks.csv', 'text/csv')
        st.caption('COMPLETED：已导出；READY/RUNNING：排队/计算中；FAILED：失败；NOT_SUBMITTED：未提交。每份结果CSV可直接导入NDVI工作台。')
