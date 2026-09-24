# 耕地 NDVI 分析工作台

## 快速使用

双击 `ndvi_workbench.html`，用 Chrome / Edge 打开。无需安装、服务器或联网；页面没有 CDN、字体或遥测请求。点击“加载20图斑示例”体验，或拖入 GEE CSV。可一次导入多年度、多批次文件。刷新只恢复阈值配置，不保存原始 CSV，需重新导入。

左侧调节阈值并开始分析；修改阈值实时重新分类，修改间隔、平滑窗口或生长季重新预处理。概览包括占比和散点图；结果支持类别筛选、ID搜索、列排序、50条分页与筛选导出。点击行进入曲线，查看原始点、平滑线、峰值、阈值和生长季。对比页可选择2–6个图斑年份（按Ctrl/Command多选），按DOY对齐比较。曲线可下载PNG。

CSV格式：

```csv
plot_id,date,NDVI,valid_pixels,NDVI_std
0001,2024-04-01,0.32,35,0.08
0001,2024-04-11,,0,
```

必需列为 plot_id/date/NDVI，容忍大小写与列名空格。ID为文本；可选质量列保留在源CSV，当前分析不以它们筛选。日期支持 YYYY-MM-DD、YYYY/MM/DD、YYYY.MM.DD（也接受带时间的日期，以前面的日历日期为准）；无效日期和空ID行跳过。NDVI空值、非数字或越界记为缺失。不得把缺失NDVI填0。全缺失图斑年份跳过；重复ID与日期取有效值均值。日期跨年时分别处理，每条结果为图斑—年份。

## 算法约定

每年1月1日起按固定间隔重采样，默认10天；仅在有效观测日期覆盖的区间内线性插值，不做首尾外推，不跨年插值。内部长缺口仍会插值，需要依据原始点复核。有效数据点不足5个以原始唯一有效日期数为准，不能用插值增加的点绕过检查；生长季没有真实观测也判数据不足。

S-G为二阶局部最小二乘，默认5点，边缘窗口平移拟合；窗口自动降为可用最大奇数，少于5点不平滑。不裁剪平滑值，避免扭曲峰值，但可能轻微超出原值范围。每年独立统计生长季（默认4–10月）平滑曲线：最大值、P95−P5、均值、峰值DOY（多峰相等取最早）。跨年月份设置如11–3表示同一日历年的1–3月及11–12月，非跨年农业季。

| 参数 | 默认 | 规则 |
|---|---:|---|
| T1 | 0.50 | 峰值低于该值 → 疑似未种植 |
| T2 | 0.35 | 生长季均值低于该值 → 疑似未种植 |
| T3 | 0.42 | 振幅低于该值 → 疑似撂荒 |
| T4 | 0.60 | 水稻峰值下限 |
| T5 | 0.42 | 水稻振幅下限 |
| P1/P2 | 180/260 | 水稻峰值DOY范围（可关闭） |

严格按上述优先顺序判定：数据不足5、疑似未种植4、疑似撂荒3、符合水稻条件1、其余疑似其他作物2。默认关闭多年确认；开启后，连续至少2年疑似未种植/撂荒的整段年份升级为“撂荒地（确认）”6。缺年、数据不足及其他类别会中断连续段。这是规则确认，不是遥感精度或行政认定，需已知样点校准及现场核验。

## 导出与复现

导出当前筛选结果CSV（UTF-8 BOM）：plot_id,year,ndviMax,ndviAmp,ndviMeanGs,peakDoy,className,classCode。Excel的自动格式识别仍可能去掉纯数字ID前导零，使用“数据→从文本/CSV”并将plot_id设为文本。以公式符号开头的ID会在CSV中添加单引号防止执行。阈值JSON可导出、导入；localStorage不可用时页面提示使用JSON。示例覆盖20个ID、2023/2024两年、5种基础类别；开启连续确认可产生第6类。示例为人工模拟，不能作为精度验证数据。

## 标准 GEE Code Editor（推荐）

下载 `gee_code_editor.js`，粘贴到 https://code.earthengine.google.com/ 。只修改顶部矢量Asset导入行和年份；如果已在Imports导入矢量为table，使用 `var plots = table;`。本地SHP需先上传GEE Table Asset，Code Editor不能直接读取电脑路径。

点击Run后，脚本校验面图斑和ID，自动生成按年、每1000图斑一批的Drive任务。在Tasks逐个点击Run，完成后下载 `ndvi_ts_年份_b批次.csv`。网页可同时选择所有这些CSV，自动合并，无需自己处理列名、日期或空值。默认10天合成、SCL云掩膜，CSV固定为plot_id/date/NDVI/valid_pixels/NDVI_std。空时段NDVI为空而不是0；不按面积自动删除小图斑。

优先保留非空唯一plot_id；否则自动使用plot_加system:index，所有年份保持一致。额外生成 `ndvi_ts_id_mapping.csv` 对应原地块属性，仅用于回连原矢量，不要导入NDVI网页；重新上传Asset可能改变自动ID，跨批追加数据应继续使用同一个Asset。影像有效性、配额和导出速度取决于GEE服务，需已授权账号与Cloud项目。代码已做语法检查，未代用户提交真实云端任务。

以下Python版本保留给需要命令行批量执行的技术人员。

## GEE导出

先准备已启用并注册 Earth Engine 的 Google Cloud 项目、GEE账户及 Drive 权限。GEE环节会把研究区几何发送到Google，不是本机离线处理；网页环节不上传CSV。推荐大数据预先上传为GEE Asset，小矢量可用本地SHP/GeoJSON。Asset的plot_id建议预先设成字符串且唯一。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-gee.txt
.venv\Scripts\python gee_export.py --project YOUR_PROJECT --asset projects/YOUR_PROJECT/assets/plots --start-year 2023 --end-year 2024 --authenticate
```

默认仅校验数据、建立任务计划，不提交任务；检查后加 `--submit` 真正提交：

```powershell
.venv\Scripts\python gee_export.py --project YOUR_PROJECT --asset projects/YOUR_PROJECT/assets/plots --start-year 2023 --end-year 2024 --interval 10 --cloud 60 --batch-size 1000 --submit
```

本地矢量替换 `--asset ...` 为 `--vector "D:/data/plots.shp"`。当地块过多导致请求载荷超限时，改用Asset。用 `--id-field`指定ID列；`--min-area`默认900平方米（约9个10米像元，但不能保证足够有效像元，设0关闭）；`--scale`默认10米；`--folder`为Drive目录，`--prefix`默认ndvi_ts。年份范围两端都包含；周期可选5/10/16天；任务按年和批次命名，如ndvi_ts_2024_b0001。每个任务ID记录于运行目录gee_tasks.json。重复提交可能生成重复Drive输出，先检查Earth Engine Tasks。

数据源COPERNICUS/S2_SR_HARMONIZED；影像云量小于指定阈值，SCL排除0/1/3/8/9/10/11，无数据、坏像元、阴影、中高概率云、卷云、雪。B4/B8反射率缩放1/10000，逐景NDVI后按周期中位数合成，再计算地块均值/标准差/有效像元数。没有有效影像的窗口仍导出每个图斑空NDVI。统计明确指定EPSG:6933和10米尺度以避免合成影像默认投影问题。valid_pixels是合成后的有效像元计数，不是观测次数。

脚本不下载影像，CSV输出到Drive后手动下载并导入HTML。SCL不能完全消除薄云，大田与小碎斑、常绿植被、双季稻等需本地校准；一期不含Sentinel-1。

## 开发与验证

`core.js`独立算法，`page.html`页面源模板，执行 `python build.py` 将算法内嵌生成单文件HTML。交付使用只需HTML，其他文件用于开发。执行 `node test_core.js`验证CSV、日期、插值、S-G二次多项式恢复、分类顺序、多年缺年处理和示例类别，并生成example_20plots.csv。

本机1000个图斑年份纯算法约40毫秒预处理、不到1毫秒分类；不含CSV解析、图表和DOM渲染，不代表所有电脑上的耗时。浏览器使用分批预处理和表格分页，特大CSV依然受内存限制。GEE实际执行依赖账户配额、影像数量、区域与队列；未用真实授权账户提交任务，不能保证1000图斑在30分钟完成。


网页实测：本机浏览器导入37,000条记录（1,000图斑、1年），页面报告分析与更新0.07秒（不包含文件读取解析）。已人工验证示例曲线、筛选、分页、对比、CSV下载和刷新恢复配置。实际耗时随电脑、图斑数和年度数变化。


默认界面采用导入后自动初筛，技术阈值收进“专业设置”。结果表、曲线与CSV提供判定依据和复核建议；有效观测间隔超过60天时提示优先复核。当前仍是可解释规则初筛，不是影像分类模型，未使用输入数据未经监督地自定类别阈值。要实现可靠影像判别，需接入时相影像特征及当地已核实的作物/撂荒样本，并完成独立精度验证。

## 分类矢量导出
网站新增“NDVI vector”页面：在工作台导出分类CSV，上传分类CSV及含相同唯一ID的原图斑，选择编号字段和年份，生成WGS84 Shapefile ZIP。多个CSV支持合并，重复图斑年份会拒绝；只导出已匹配图斑，未分析记录不会被赋予分类。关联步骤在Streamlit服务器处理，原有浏览器CSV分析仍在本地完成。输出包含ndvi_year、ndvi_max、ndvi_amp、ndvi_mean、peak_doy、class_name、class_code及字段说明。
