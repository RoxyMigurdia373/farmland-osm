# 在线GEE试验配置与回退

稳定备份提交：91e3677；Git标签：backup-before-gee-online-20260924。
本机完整源码备份位于项目父目录 farmland_osm_backup_before_gee_online_20260924.zip，不包含用户数据或密钥。

新功能仅位于 pages/2_GEE_online.py 和 gee_online.py，原NDVI HTML及空间分析逻辑不变。
限制每次100块、一个完整年份、几何JSON不超过4MB；这是同步小批量试验，不是后台任务队列。页面关闭或Streamlit重启可能丢失任务会话。大批量继续使用标准GEE脚本。

## 管理员配置

在Google Cloud控制台建立OAuth同意屏幕与Web application类型客户端，注册Earth Engine项目并启用API。配置测试用户（处于Testing状态时只有名单内账号可用）。所需OAuth权限为earthengine与cloud-platform；这些权限不只覆盖本次矢量，请在同意屏幕明确说明。正式面向外部用户开放可能需要Google审核。

Authorized redirect URI必须精确为：
https://farmland-osm-roxy.streamlit.app/GEE_online

在Streamlit Cloud应用Settings → Secrets添加（不要提交到GitHub）：

```toml
[gee_oauth]
client_id = "Google OAuth Web客户端ID"
client_secret = "Google OAuth客户端密钥"
redirect_uri = "https://farmland-osm-roxy.streamlit.app/GEE_online"
default_project = "已注册Earth Engine的项目ID"
```

用户仍需Earth Engine使用资格和对所填项目的权限。Google登录成功不代表EE项目权限可用。不要求用户提供密码或粘贴令牌。
授权使用state与PKCE。若Google在新标签返回导致Streamlit会话丢失，保留原标签页，将返回网址粘贴到原页“恢复授权”，原会话将校验state、10分钟有效期并交换code。返回网址含一次性授权码，不要发给别人。原页也关闭则重新授权。

访问令牌仅保存在当前会话内，不写入磁盘或全局缓存，不请求离线refresh token。55分钟后要求重新授权；退出清除会话，不等于从Google账号撤销应用授权，可到Google账号权限管理撤销。EE Python SDK使用进程全局状态，因此试验提取采用互斥锁，且结束后ee.Reset，避免跨用户凭证串用。

用户上传文件经服务器读取，并在明确勾选同意后发送几何至Google。结果返回会话后自动进入浏览器内NDVI工作台，可下载标准CSV和ID对应表。当前尚未使用真实OAuth凭证联调，不能宣称云端流程验收通过。

## 快速回退

只关闭试验功能：删除/撤下pages/2_GEE_online.py后提交推送，或删除Secrets中的gee_oauth配置使入口停用。
完整回退：先备份当前未提交修改，执行 `git restore --source backup-before-gee-online-20260924 -- .`，再删除该备份版本不存在的新增试验文件，检查差异并创建回退提交后push；不要强制改写远端历史。也可对本次试验提交执行git revert。GitHub标签保留稳定源码可下载。
