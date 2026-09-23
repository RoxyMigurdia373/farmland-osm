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

### 完整 OSM 数据提取

展开页面“第一步：从完整 OSM 数据提取分析材料”，上传村界/分析范围面（ZIP 或 GeoJSON），以及完整 OSM ZIP 或多个图层 ZIP。范围默认外扩 1000 米，可改为 0；提取与范围相交的完整地物，不截断边界。分别下载 `road_materials.zip`（公路、铁路）和 `village_materials.zip`（村庄点面、居民区用地），均为 Shapefile 压缩包，可直接上传到下方 OSM 分析入口。压缩包含 `.shp/.shx/.dbf/.prj/.cpg` 及字段映射文件；某类没有匹配数据时显示提示，不生成空文件。

Geofabrik 建议只上传 4 类文件：`gis_osm_roads_free_1.shp`（道路）、`gis_osm_railways_free_1.shp`（铁路）、`gis_osm_places_free_1.shp`（村庄点）、`gis_osm_landuse_a_free_1.shp`（居民区面），并带齐 shp/shx/dbf/prj/cpg。roads 的 fclass 转为 highway，railways 转为 railway，places 转为 place，landuse 转为 landuse。只保留已有分析逻辑可识别的道路、铁路、village/hamlet/town 和 residential 用地；建筑图层不会当作村庄。保留名称和 OSM ID，输出 WGS84。一般 GeoJSON/自定义图层建议直接含标准分类字段；不含标准字段的自定义 fclass 只转换明确可识别的道路与村庄值。

范围可包含多个村，合并提取。过小的范围可能遗漏外部最近地物，建议外扩距离不小于分析阈值。每个上传文件最多 500 MB，ZIP 解压后最多 2 GB；广东完整数据较大时请按图层连同 shp/shx/dbf/prj/cpg 打包，而不是上传本机目录路径。云端不能直接读取本地磁盘路径。提取按范围过滤读取，仍需为大数据预留处理时间及服务器空间。

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

位置描述采用项目约定的国内道路名称：高速公路、国道、省道、县道、乡道、村道、专用道路、机耕道/生产路、田间小路、人行道、非机动车道。连接线归入对应大类，不显示具体路名及英文类型；该映射不构成法定行政等级认定。

侧边栏“显示方位”“显示距离”可独立勾选，默认均关闭。默认写“乡道旁”“村道旁”“铁路旁”“XX村居民点旁”（无村名为“村庄旁”）；仅方位写“位于乡道东侧”，仅距离写“乡道旁约85.20米”，两项都开写“位于乡道东侧约85.20米”。距离不超过 0.005 米时不附加距离文字。开关只控制位置描述，最近距离字段、最近地物选择和距离阈值始终正常计算。

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


Shapefile 导出按几何类型分层：混合数据使用 result_points、result_multipoints、result_lines、result_polygons，均置于同一个 ZIP。村庄点与居民区面不会互相转换或丢弃；整个 ZIP 可直接重新上传分析。单一类型仍使用 result 图层名。


### 双范围与中心坐标

位置选择样式可选“单一最近地物”或“双范围位置（200米 / 500米）”。双范围增加各自的位置类型、地物子类、最近距离、位置描述字段，按未舍入距离判断是否在范围内；无匹配时类型为“无”、距离留空。这是两个半径内的最近地物，并非200–500米环带或所有地物清单。若最近地物在200米以内，两组结果相同；双范围独立于原最大距离阈值。

勾选“输出地块中心经纬度”后，计算米制分析投影下的面积重心并转换为 WGS84 十进制度，保留8位小数；凹面或多部件面的中心可能位于面外。Shapefile 字段为 center_lon、center_lat；双范围字段为 r200_type/sub/dist/desc 和 r500_type/sub/dist/desc，附中文字段映射。

按项目约定，trunk及其连接线表述为国道，primary及其连接线表述为省道，residential和living_street统一表述为村道。这是项目命名约定，不代表OSM已核验国内行政道路等级。
