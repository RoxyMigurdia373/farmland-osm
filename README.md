# 耕地地块周边地物分析工具

Python 3.10+ / Streamlit，上传耕地和 OSM 矢量，计算每个图斑到最近公路、铁路或村庄的最短距离，导出 WGS84 GeoJSON 与 Shapefile。

## 在线使用

访问 https://farmland-osm-roxy.streamlit.app/ ，无需在本机安装 Python。应用部署在 Streamlit Community Cloud，数据上传至该托管服务器处理。

`tests/fixtures/farmland.geojson` 和 `tests/fixtures/osm.geojson` 是人工构造的两个地块及路网示例，可用于试用；最近距离应分别为 10 米和 80 米，启用 50 米阈值后第二块应标为“无”。

## 本地运行

在本项目目录执行（需先安装 Python 3.10+）：

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux 使用 source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

浏览器访问终端给出的本机地址。必须从本项目目录启动，以加载 `.streamlit/config.toml` 的 500 MB 单文件上传限制。依赖安装完成后，应用无需联网即可运行；完全离线环境需提前准备对应平台的依赖 wheel 包。

## 使用

1. 上传耕地面图斑 ZIP 或 GeoJSON。
2. 上传一个或多个 OSM ZIP / GeoJSON，可混合不同坐标系。
3. 按需启用距离阈值（默认 1000 米，默认不启用）。
4. 点击“开始分析”，查看统计和前 100 行属性，下载所需格式。

ZIP 中每套 Shapefile 必须包含同名 `.shp/.shx/.dbf/.prj`，建议包含正确声明字符编码的 `.cpg`。允许子目录及多套 Shapefile，程序会统一坐标系并合并。单 ZIP 解压总大小限制 2 GB，最多 10000 个文件。GeoJSON 通常按标准使用 WGS84，经纬度坐标不能伪装为投影坐标。

耕地仅接受 Polygon / MultiPolygon，OSM 接受点、线、面及其 Multi 类型。侧边栏默认启用“自动修复无效几何”：使用 make_valid 修复自相交等拓扑错误，耕地修复为几何集合时提取面部分，保留原属性和行顺序。空几何、退化后无面或无法可靠修复的记录会跳过，不进入分析与结果；界面显示各文件输入、修复、跳过及保留数量，并提供处理明细 CSV（原始行号从 1 开始；ZIP 多图层使用合并顺序）。修复可能改变形状和面积，请复核。全部耕地被跳过时停止分析。关闭该选项后恢复严格校验，发现无效几何即停止。缺失坐标系不能自动修复。输入含同名输出字段时停止，避免覆盖原属性。

## 分类和距离

优先按 `railway` 有值 → 铁路，`highway` 有值 → 公路，`place` 为 village/hamlet/town → 村庄，`landuse=residential` → 村庄，其余忽略。严格遵循有值规则，例如 `railway=no` 也会匹配，请按需预清洗数据。兼容大小写、前后空格、`osm_` 前缀，以及 JSON `tags`、OSM `other_tags`；无法仅凭名称或 `fclass` 猜测分类。

以耕地图斑范围估算 UTM，所有数据转换到同一米制投影。采用 Shapely STRtree 最近邻空间索引，每 5000 个地块查询一块。计算整个图斑到整个地物的最短平面距离，而非质心距离；相交或包含为 0。距离完全相同时按铁路 > 公路 > 村庄，再按输入顺序选择。

UTM 失败后回退到以数据范围中心建立的 **WGS84 局部等距投影（AEQD）** 并显示偏差提示；不直接在经纬度上计算并将度数当米。两种投影均失败则停止。局部投影只适合局部分析，大范围、跨日期变更线或多 UTM 带数据建议拆分后运行。

超过阈值时位置类型为“无”，子类为空，描述为“不在公路、铁路或村庄周边”，仍保留真实最近距离。阈值用未四舍五入的距离比较，相等视为阈值以内。分类后无任何地物时停止并提示检查字段，不输出虚构距离。统计中的“无”类别平均值同样是实际最近距离。

## 输出字段

保留耕地原属性，新增：

| GeoJSON 字段 | Shapefile 字段 | 含义 |
| --- | --- | --- |
| 位置类型 | loc_type | 公路 / 铁路 / 村庄 / 无 |
| 地物子类 | osm_sub | OSM 属性值 |
| 最近距离 | near_m | 米，四舍五入至两位小数 |
| 位置描述 | loc_desc | 中文描述 |

位置描述明确道路中文类别，不附加英文地物类型。例如 motorway → 高速公路、trunk → 干线公路、primary → 主要公路、secondary → 次要公路、tertiary → 一般公路、residential → 居民区道路、track → 农林作业道路。连接线单独标注；无法识别的类型写“类别未明确的道路”，不猜测类别。有名称时优先使用 `name:zh`、`name_zh`、`name`，例如“位于主要公路（人民路）边，最近距离约 10.00 米”；没有名称时写“位于主要公路边”。OSM 等级不等于我国国道/省道行政等级，也不直接等于一级/二级公路技术等级。英文类型仍保留在“地物子类”字段。铁路、村庄分别写“位于铁路边”“位于村庄周边”。

GeoJSON 使用 UTF-8、EPSG:4326。JSON 数字可能省略尾随 0，但数值已保留两位小数精度。Shapefile ZIP 包含 `.shp/.shx/.dbf/.prj/.cpg` 及 `字段映射.json`。DBF 字段名限制为 10 字节，中文/超长/冲突原字段会映射为短名。复杂属性序列化为 JSON 字符串，日期时间转为文本。DBF 单文本最多 254 字节，超过时明确停止 Shapefile 导出，GeoJSON 仍可下载，避免静默截断。Shapefile 本身不能完整保留所有原始字段类型，保真优先选择 GeoJSON。

## Streamlit Community Cloud

将本目录内容作为仓库根目录推送 GitHub，在 https://share.streamlit.io 连接仓库，选择 `app.py` 作为入口，选择受支持的 Python 3.10+ 环境后部署。`requirements.txt` 会自动安装依赖，无需地图 API Key。若置于仓库子目录，请相应选择入口并将 `.streamlit/config.toml` 放在仓库根目录。

本地部署只在本机处理；Cloud 部署需要把数据上传至托管服务器。应用不会向第三方地图服务发送数据，不进行在线 OSM 查询。分析使用内存，文件读写使用服务器临时目录并在结束后自动清理；结果保留在当前 Streamlit 会话内，变更输入或分析设置即清除。敏感数据建议本地离线运行。

超过 5 万地块会提示等待。500 MB 上传上限不代表云端具有足够内存；GeoDataFrame、空间索引与下载文件都需要内存，超大数据建议本地运行或拆分。大量重叠地物产生大量并列最近邻时也会增加资源占用。

## 验证

```bash
python -m unittest discover -s tests -v
```

测试覆盖分类优先级、最短距离、阈值、并列选择、投影回退、输入错误、中文导出往返及 ZIP 路径安全。
