"""Host the standalone browser-only NDVI workbench."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="耕地 NDVI 分析工作台", page_icon="🌱", layout="wide")
root = Path(__file__).resolve().parents[1] / "ndvi"
st.caption("NDVI 分析在下方浏览器页面内完成，CSV 不上传到服务器。侧边栏可返回空间分析工具。")
with st.expander("下载离线工作台与 GEE 脚本"):
    st.write("GEE推荐方式：下载标准JavaScript → 粘贴到Code Editor → 修改顶部矢量Asset和年份 → Run → Tasks运行导出。下载各年份/批次CSV后，在下方一次性选择导入，无需改列名或合并文件。")
    st.download_button("下载标准 GEE 代码（Code Editor JS）", (root / "gee_code_editor.js").read_bytes(), "gee_code_editor.js", "text/javascript")
    st.caption("没有唯一plot_id时自动用Asset的system:index生成，并额外导出ID对应表。id_mapping.csv仅用于关联原图斑，不导入NDVI工作台。")
    st.download_button("下载单文件 HTML", (root / "ndvi_workbench.html").read_bytes(), "ndvi_workbench.html", "text/html")
    st.download_button("下载 GEE Python 脚本", (root / "gee_export.py").read_bytes(), "gee_export.py", "text/x-python")
    st.download_button("下载 GEE 依赖清单", (root / "requirements-gee.txt").read_bytes(), "requirements-gee.txt", "text/plain")
    st.download_button("下载使用说明", (root / "README.md").read_bytes(), "NDVI_README.md", "text/markdown")
st.page_link('pages/3_NDVI_vector.py', label='分类完成后：导出SHP矢量结果', icon='🗺️')
components.html((root / "ndvi_workbench.html").read_text(encoding="utf-8"), height=1000, scrolling=True)
