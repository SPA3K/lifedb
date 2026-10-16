# Kernel 层模态数据导入手册

> 大记理论 LifeDB · 2026-10-13 落盘
> 数据库：`~/.hermes/life-db/timeline.db`（单 SQLite 文件，schema v1）
> 通用约定：所有 adapter 必须有 `*.manifest.json`（注册）、支持 `--dry-run`（事务内跑完回滚）、幂等键去重（重复跑 = 0 新增）

---

## 0. 总览

| 模态 | 源 | adapter/工具 | 入库表 | 幂等键 | 频率 |
|---|---|---|---|---|---|
| GPS 轨迹 | 一生轨迹 CSV (backUpData-all.csv) | `adapters/lifetrack.py` | geo_point(秒级点) + event(停留段) | geo_point: `ts+lat+lon` 主键 OR IGNORE | 手动重导（自动去重） |
| 健身训练 | 训记 API (api.xunji.fit) | `adapters/xunji.py` | event | localid | 增量拉新日期 |
| 健康数据 | Apple 健康导出 (飞书收到 `导出.zip`) | `adapters/apple_health.py` | event(sleep/workout_route/ecg) | `ah-sleep-<sha1(起|止|段数)>` / `ah-gpx,ah-ecg-<sha1(文件名)>` | 手动 (每次新导出包) |
| 交通位移 | Google Timeline 导出 | `adapters/gmaps.py` | event(visit→location, activity→transport) + geo_point | 条目 hash | 每月导出追加（Google 只留 3 周） |
| 照片/视频 | iCloud 照片 (国区) | `sync/icloud_sync.py` 下载 + `adapters/photo.py` 入库 | event | `sha1(relpath\|size)` | 每小时 cron 自动 |

CLI（Git Bash 下用 `py -3 life-db <cmd>`，shebang 不生效）：
```
life-db adapters          # 列出已注册 adapter
life-db query <YYYY-MM>   # 按月时间线
life-db around "HH:MM"    # 跨模态事件窗
life-db stats             # 覆盖统计
```

---

## 1. iCloud 照片（★ 本次重点，含 Apple ID 交互式登录方案）

### 1.1 链路全景

```
icloud_auth.py (一次性认证, ~2个月有效)
      ↓ cookie ~/.pyicloud/{account} + .session
icloud_sync.py (每小时 cron) → icloudpd 下载 → D:\icloud-photos\%Y\%m\%d\
      ↓
adapters/photo.py → timeline.db (event, source=icloud)
      ↓
~/.hermes/scripts/life_db_photo_ingest.py (cron d7c7a2ae03d3, 每小时:17)
```

### 1.2 Apple ID 交互式登录方案（`sync/icloud_auth.py`）

**用法**：
```bash
py -3 icloud_auth.py               # 交互式：触发一次 → 等推送 → 输入最新 6 位验证码
py -3 icloud_auth.py --code 123456 # 非交互：预置验证码
tail -f sync/icloud_auth.log       # 全程进度可见
```

**认证四步曲（按序排查，每步都实证过）**：

| 步骤 | 现象 | 根因 | 解法 |
|---|---|---|---|
| 1 | `-20283 Invalid email/password`（用应用专用密码） | 新版 pyicloud 走 **SRP 流程只认真实密码**，应用专用密码已被 Apple 拒绝 | conf 里填 Apple ID **真实密码** |
| 2 | `Apple insists on using iCloud.com.cn` | 中国区账号（云上贵州 GCBD） | `DOMAIN=cn` |
| 3 | `Please enter two-factor authentication code` 卡住 | MFA 交互（详见下方三大坑） | **用 `icloud_auth.py`，别手工喂码** |
| 4 | `Missing X-APPLE-WEBAUTH-TOKEN cookie` / `Apple iCloud setup is not complete` | 国区账号网页端条款/隐私声明未确认，服务未初始化 | 登录 https://www.icloud.com.cn 同意条款 → 重跑 `icloud_auth.py`（信任浏览器复用，**二轮认证连验证码都不弹，7 秒完成**） |

**脚本设计的三大坑（每一个都真实卡死过，改脚本必须保留这些处理）**：

1. **MFA 提示无换行符**：`Please enter two-factor authentication code or device index (a)...` 后面**没有 `\n`**。按行读（`for line in proc.stdout`）永远等不到这一行 → 检测器不触发 → 码卡在管道里。**必须逐字符读 + 缓冲区正则扫描**。
2. **`isatty()` 不可靠**：某些 pty/代理环境下 `sys.stdin.isatty()` 返回 False 但 `input()` 实际可用。用 isatty 判断会导致"非交互环境"误判直接退出。**直接 try input()，EOFError 才判定不可交互**。
3. **选项类提示会浪费验证码**：`Please choose an option` / `Which device would you like to use` 这类提示要的是菜单序号或回车（选默认项），不是 6 位码。若和码提示混为一谈，会拿用户给的码去回答菜单 → 流程错乱双双卡死。**选项类提示自动回车，只有码提示才消耗验证码**。

**其他要点**：
- **单实例锁**：`~/.pyicloud/.auth_lock`（PID 文件 + psutil 存活检查，stale 自动清）。没有它，两个并发认证进程 = Apple 连环弹窗 = 用户不知道该输哪个码
- **"弹两次验证码"的两个来源**：① icloudpd 内部两轮认证（第一轮验密码、第二轮建 cookie，官方 issue #280）；② 并行的探测进程各自发请求。单实例锁 + parameter 密码模式下实测**只需一轮**
- **成功判据**：日志出现 `Authentication completed successfully` + cookie 文件 mtime 更新。失败串：`Incorrect verification code`（-21669 = 码过期/已用，重跑即可）
- **cookie 有效期约 2 个月**。到期 `icloud_notify.py` 自动发飞书提醒（已实测），重跑本脚本续期
- **-20283 频繁出现 = Apple 密码验证节流**：当天多次失败后触发，等几十分钟自然恢复，期间别硬试（越试锁越久）

### 1.3 下载（`sync/icloud_sync.py`）

```bash
py -3 icloud_sync.py                # 单次增量同步（cron 用）
py -3 icloud_sync.py --watch        # 常驻（watch-with-interval）
py -3 icloud_sync.py --auth-only    # 转发给 icloud_auth.py
py -3 icloud_sync.py --dry-run      # icloudpd 原生 dry-run
```

配置集中在 `sync/icloud.conf`（密码只落本机文件，不进 git）：
```
APPLE_ID=...  PASSWORD=...  DOMAIN=cn
ICLOUD_DIR=D:\icloud-photos
FOLDER_STRUCTURE={:%Y/%m/%d}
RECENT=            # 留空=全库；数字=只下最近 N 张
WATCH_INTERVAL=3600
```

**关键参数（已固化，别删）**：
- `--size original` 下原图（photo adapter 要 EXIF）
- `--set-exif-datetime` 无 EXIF 时间的用文件创建时间补（adapter 另有 mtime 兜底）
- `--notification-script icloud_notify.py` 2FA 过期/认证失败 → 飞书告警

### 1.4 按时间窗下载（缓存分层的核心能力）

**全库 13,994 个资产，D 盘只剩 43G，装不下全库 → 时间窗是刚需。**

```bash
# 只下指定日期窗内的资产（含两端，exclusive 语义实测：before=起点含, after=终点不含）
icloudpd ... --skip-created-before 2026-10-11 --skip-created-after 2026-10-12
```
实测（2026-10-13）：窗口 [10-11, 10-12) 精确下载 12 个文件，全部落在 `2026/10/11` 目录，无越界。

**注意**：
- `--only-print-filenames` 在 cn 域下不输出（已知怪癖），验证窗口直接下到临时目录看结果
- `--recent N` 只下最近 N 张（与时间窗可叠加）
- 全库体积未知，制定全量/分层策略前先抽样估算（例：随机几天的窗口看平均日增）

### 1.5 photo adapter 入库

```bash
py -3 adapters/photo.py "D:\icloud-photos" --dry-run   # 先 dry-run
py -3 adapters/photo.py "D:\icloud-photos"             # 正式入库
```
- 时间戳三级兜底：EXIF DateTimeOriginal > EXIF DateTime > 文件 mtime
- EXIF GPS → 十进制 lat/lon（event 表列，可与 geo_point 跨模态关联）
- Live Photo：同名 `.JPG`+`_HEVC.MOV` 配对合并为一行，`meta.live=true`，视频半不单独成行
- 幂等：`payload_hash = sha1(relpath|size)`，UNIQUE(source, payload_hash) + INSERT OR IGNORE
- 验证（2026-10-13 实测）：首批 30 张入库，重跑 = 0 新增；Live 配对 2 组正确合并

### 1.6 Apple 健康导出 (`adapters/apple_health.py`)

```bash
py -3 adapters/apple_health.py                # 自动找 ~/.hermes/cache/documents 下最新导出包
py -3 adapters/apple_health.py <export.zip>   # 指定包
py -3 adapters/apple_health.py --dry-run      # 试跑 (事务回滚)
```

- **睡眠分期** (SleepAnalysis → event modality=sleep): 会话切法 = **间隙聚类** (相邻记录 >3h 断开); 按日期分组会把凌晨 05:xx 的续段链成 24h 长串 (踩过: 309 vs 37)
- **InBed 必须映射后排除**，否则 `else→other` 混入会话 (踩过: 首跑 309 条全是 InBed 污染)
- meta.stages_iso 带时区 ISO (`+08:00`) → 下游 (replay 睡眠面板) 直读绝对时间, 无时区歧义; 回放参考夜选择/重映射在 `visual/replay_day.py`
- GPX 锻炼轨迹 → `store/apple_health/routes/` + event(workout_route); Apple GPX 是 **lon 在 lat 前 + 单行紧凑**格式, 正则不能假设 lat 优先
- ECG CSV → `store/apple_health/ecg/` + event(ecg)
- 导出.xml ~1GB, 流式解析 ~4min; 重复跑幂等零副作用 (2026-10-15 首批: 37 睡眠会话 2022-03→2025-07 + 172 gpx + 13 ecg)

---

## 2. 训记健身

```bash
py -3 adapters/xunji.py --dry-run
py -3 adapters/xunji.py            # 增量：缓存已有断点续跑，只拉新日期
```
- Key 全量值：`grep -o "xjllm_[a-f0-9]*" <用户发的API文档>`（env 文件里是缩略版）
- 响应 **gzip 压缩**：`gzip.decompress(r.content)` 再 json.loads
- 端点 `GET https://api.xunji.fit/...?datestr=YYYYMMDD`，每训练日一条
- 幂等键：localid；原始响应缓存在 `adapters/_xunji_cache/`
- 限速 0.4s/天（文档说 15s/训练日，实测无拦截，温和即可）

## 3. 一生轨迹 GPS

```bash
py -3 adapters/lifetrack.py --dry-run
py -3 adapters/lifetrack.py <backUpData-all.csv路径>
```
- 两层入库：秒级点 → geo_point（主键 `ts+lat+lon` OR IGNORE，多源自动互补）；停留段（≥15min、≤150m、断点>30min 切段）→ event
- 已入库 294,811 点 + 833 停留段（2015-07 → 今）
- 重导安全：主键去重，重复跑 = 0 新增

## 4. Google Timeline

```bash
py -3 adapters/gmaps.py --dry-run
py -3 adapters/gmaps.py <Timeline.json路径>
```
- 新版导出三类条目：visit → location(event)；activity → transport(event)；timelinePath → geo_point
- **Google 只留约 3 周数据 → 每月导出一次追加**
- 首尔行时区混 +08/+09，查询时注意
- geo_point 与一生轨迹 CSV 跨源自动去重（实测 1 点重叠被主键吞掉）

---

## 5. 通用排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 认证反复失败 | Apple 节流 | 等 30-60 分钟再试 |
| `Authentication required (421)` | cookie 失效/不完整 | 重跑 `icloud_auth.py` |
| `Photo Library has not finished indexing yet` | 账号新开通，服务端索引中 | 等（分钟到小时级），cron 会自动重试 |
| `python3` 无输出 rc=49 | Windows Store shim 是坏的 | 用 `python`（miniconda）或 `py -3` |
| pty 后台进程输出全空 | 工具层缓冲问题 | 看落盘日志（`icloud_auth.log` 等），别误判卡死 |
