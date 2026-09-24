"""Experimental page; does not alter the existing analysis workflow."""
import datetime
import json
import secrets
import time
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import gee_online
import importlib
if not hasattr(gee_online, 'validate_config'):
    importlib.reload(gee_online)
from gee_online import authorization, exchange, extract, validate_config
from io_utils import read_vector
from analyzer import repair_geometry, validate_geometry

st.set_page_config(page_title='在线GEE试验', page_icon='🛰️', layout='wide')
st.title('在线 GEE 分析 · 试验版')
st.write('Google授权 → 上传耕地矢量 → 提取NDVI → 自动进入分类工作台')
st.info('直接上传支持100个图斑；大批量入口支持最多15万图斑的GEE资产分批后台导出，每次分析1年。现有空间分析和CSV分析入口仍可单独使用。')
try:
    config = dict(st.secrets['gee_oauth'])
except (KeyError, FileNotFoundError):
    config = {}
required = ['client_id', 'client_secret', 'redirect_uri']
if not all(config.get(k) for k in required):
    st.warning('管理员尚未配置Google OAuth，此入口暂不可登录。现有NDVI工作台可继续使用。')
    st.markdown('请管理员按 GitHub 仓库 GEE_ONLINE_SETUP.md 配置后启用。用户无需提供密码或自行复制授权令牌。')
    st.stop()
try:
    config = validate_config(config)
except ValueError as exc:
    st.error(str(exc))
    st.caption('管理员请在Streamlit Secrets中修正配置；不要在聊天或GitHub中公开密钥。')
    st.stop()

# Discard old authorization URLs after the administrator changes client settings.
config_version = __import__('hashlib').sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
if st.session_state.get('gee_config_version') != config_version:
    for key in list(st.session_state):
        if key.startswith('gee_'):
            del st.session_state[key]
    st.session_state.gee_config_version = config_version

if st.button('退出授权 / 清除本会话数据'):
    for key in list(st.session_state):
        if key.startswith('gee_'):
            del st.session_state[key]
    st.query_params.clear()
    st.rerun()

# Manual callback paste keeps PKCE/state in original session if OAuth redirects open a new websocket.
st.caption('授权在新标签页完成。若返回后未自动登录，可将返回网址粘贴到原页面的“恢复授权”中；不要发送给他人。')
from urllib.parse import urlparse, parse_qs
callback = dict(st.query_params)
with st.expander('恢复授权（仅返回后未登录时使用）'):
    callback_url = st.text_input('Google返回的完整网址', type='password', key='gee_callback')
    if st.button('完成授权') and callback_url:
        callback = {k: v[0] for k,v in parse_qs(urlparse(callback_url).query).items()}
if 'code' in callback:
    expected = st.session_state.get('gee_state', '')
    if expected and secrets.compare_digest(str(callback.get('state', '')), expected) and time.time() - st.session_state.get('gee_auth_time',0) < 600:
        try:
            st.session_state.gee_token = exchange(config, callback['code'], st.session_state.gee_verifier)
            st.session_state.gee_token_time = time.time()
            st.session_state.pop('gee_state', None)
            st.query_params.clear()
            st.success('授权成功。')
        except ValueError as exc:
            st.error(str(exc))
        except Exception:
            st.error('授权失败或已过期，请重新发起登录。')
    else:
        st.warning('此标签页没有原始授权会话。请回到原页面，在恢复授权中粘贴当前返回网址。')
if time.time()-st.session_state.get('gee_token_time',0)>3300:
    st.session_state.pop('gee_token', None)
if 'gee_token' not in st.session_state:
    if st.button('准备 Google 登录'):
        url,state,verifier = authorization(config)
        st.session_state.update(gee_auth_url=url, gee_state=state, gee_verifier=verifier, gee_auth_time=time.time())
    if st.session_state.get('gee_auth_url'):
        st.link_button('前往 Google 授权', st.session_state.gee_auth_url)
    st.stop()

mode = st.radio('处理方式', ['小范围直接分析（100图斑）', '大批量后台导出（15万图斑）'], horizontal=True)
if mode == '大批量后台导出（15万图斑）':
    from gee_batch import render
    render(st.session_state.gee_token)
    st.stop()

project = st.text_input('已注册 Earth Engine 的 Google Cloud 项目 ID', value=config.get('default_project',''))
upload = st.file_uploader('上传耕地图斑 ZIP / GeoJSON', type=['zip','geojson','json'], key='gee_upload')
year = st.number_input('分析年份', min_value=2017, max_value=datetime.date.today().year-1, value=datetime.date.today().year-1)
accepted = st.checkbox('同意将本次上传的图斑几何发送至Google Earth Engine进行分析')
if st.button('开始云端提取并分析', disabled=not(upload and project and accepted)):
    st.session_state.pop('gee_csv',None)
    try:
        frame = read_vector(upload.getvalue(), upload.name)
        frame,report,_ = repair_geometry(frame, farmland=True)
        validate_geometry(frame, farmland=True)
        st.write(f"修复{report['修复数']}条，跳过{report['跳过数']}条，保留{len(frame)}条。")
        if 'plot_id' not in frame or frame.plot_id.isna().any() or frame.plot_id.astype(str).duplicated().any() or frame.plot_id.astype(str).str.strip().eq('').any():
            frame['plot_id'] = [f'plot_{i+1:06d}' for i in range(len(frame))]
            st.warning('已按修复后行顺序生成plot_id，请下载ID对应表保存关联关系。')
        frame['plot_id'] = frame.plot_id.astype(str)
        st.session_state.gee_mapping = frame.drop(columns=frame.geometry.name).to_csv(index=False).encode('utf-8-sig')
        with st.spinner('GEE计算中，请保持页面打开；不支持关闭网页后的后台续跑。'):
            rows = extract(frame[['plot_id',frame.geometry.name]], project.strip(), st.session_state.gee_token, int(year), st.progress(0).progress)
        st.session_state.gee_csv = pd.DataFrame(rows).reindex(columns=['plot_id','date','NDVI','valid_pixels']).to_csv(index=False)
    except Exception as exc:
        import re
        detail = str(exc).replace(st.session_state.get('gee_token', ''), '[令牌隐藏]') if st.session_state.get('gee_token') else str(exc)
        detail = re.sub(r'https?://\S+', '[请求地址隐藏]', detail)
        st.error(f'诊断：{type(exc).__name__}: {detail[:1500]}')
        st.error('云端提取失败：请检查项目是否启用Earth Engine、账号权限、授权是否过期或配额。可重新授权后重试；大批量数据请使用标准GEE脚本。')
if st.session_state.get('gee_mapping'):
    st.download_button('下载图斑ID对应表', st.session_state.gee_mapping, 'plot_id_mapping.csv', 'text/csv')
if st.session_state.get('gee_csv'):
    csv = st.session_state.gee_csv
    st.download_button('下载标准NDVI CSV', csv.encode('utf-8-sig'), 'ndvi_online.csv', 'text/csv')
    page = (Path(__file__).resolve().parents[1]/'ndvi'/'ndvi_workbench.html').read_text(encoding='utf-8')
    # Escape all HTML-sensitive bytes before embedding untrusted IDs/data in script.
    payload = json.dumps(csv, ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    page = page.replace('</html>', '<script>loadText('+payload+');</script></html>')
    components.html(page, height=1000, scrolling=True)
