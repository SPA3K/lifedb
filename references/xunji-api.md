# 训记训练数据 Open API Skill

## 原则
- 只在用户明确要求读取、整理或写回训练数据时调用接口。
- 写回前必须先展示变更摘要，并等待用户确认。
- 按 `datestr` 缓存读取结果；同一天不要重复请求。

## 鉴权
- 请求头: `Authorization: Bearer xjllm_84866d3e3bfefdcbf7b30ef31c172f9e854cebc398b5a1ea`
- 也兼容请求头 `x-api-key`。
- 不支持把 Key 放在 body 或 query 里。
- 不要把 Key 写入日志或展示给第三方。

## 接口
- 训练记录 Base URL: `https://trains.xunjiapp.cn`
- 读取训练: `POST /api_trains_for_llm_v2`
- 写回训练: `POST /api_upsert_trains_for_llm_v2`
- 官方计划 Base URL: `https://api.xunjiapp.cn`
- 读取官方计划: `POST /open/plan/query_gzip`
- 成功时核心数据在 `res`；不要要求返回里必须有 `success === true`。
- 标准动作中文名: `https://github.com/Foveluy/Xunji-movements`

## 读取
```http
POST https://trains.xunjiapp.cn/api_trains_for_llm_v2
Authorization: Bearer xjllm_84866d3e3bfefdcbf7b30ef31c172f9e854cebc398b5a1ea
Content-Type: application/json

{
  "schema_version": "train_open_api_v2",
  "datestr": "2026-04-02",
  "include_full_data": false
}
```

- 默认 `include_full_data: false`，只返回适合普通读取的轻量数据。
- 需要未打勾组、RPE、备注、完成感受、左右侧重量、实练秒数、动作预设休息秒数或每组实际休息秒数时，传 `include_full_data: true`。
- 动作休息设置单位为秒：`restTime` 对应正式组，`warn_restTime` 对应热身组（`sets[].setType: "热"`），已设置时在完整数据中返回。`sets[].restSeconds` 是实际已休息时长，不是休息目标。
- 有氧、计时、Tabata、苹果健康等记录型动作会在 `sets[].metrics` 返回 distance/kcal/calories/workoutTime/avgHeartRate/maxHeartRate/minHeartRate 等摘要指标。
- 获取心率数据时，必须用 `include_full_data: true` 读取。普通训练 note 里的整次训练心率在 `trains[].heartRate`；有氧/苹果健康等动作级心率摘要在 `sets[].metrics.avgHeartRate/maxHeartRate/minHeartRate`，压缩趋势在 `sets[].heartRate`。
- `sets[].heartRate` 字段包含 `avg/max/min/duration/count/step/values/peak`；`values` 最多 50 个分桶平均 BPM 点，第 N 个点的时间约为 `N * step` 秒。接口永远不返回原始心率数组。
- 如果训练没有 `trains[].heartRate`，各组也没有心率摘要或 `heartRate`，说明这次训练没有可导出的心率数据；不要因为缺少 `heartRates` 原始数组就判断失败。
- 苹果健康训练的 `name` 返回运动类型，例如 `Running`；老数据会尽量从训练标题推断。
- 超级组会在 `sets[].items[]` 返回子动作；普通递减组会在 `include_full_data: true` 时返回 `sets[].dropSets[]`。
- 返回里的训练在 `res.trains`；写回旧训练时保留 `localid`、`start`、`end`。
- 动作不会暴露内部 key；需要标准动作名时读取 GitHub 动作名表。

## 读取官方计划
- 官方计划读取包括用户正在使用的 PlatformPlan 和 UniversalPlan，仅支持读取。接口使用本 Skill 中同一个训练数据 Key；调用前用户必须先在 App 申请 Key。
- 接口返回 gzip 压缩 JSON（`Content-Encoding: gzip`）。大多数 HTTP 客户端会自动解压；不会自动解压时，先解 gzip 再解析 JSON。
- 先列出计划，再使用返回的 `plan_ref` 查询日期范围。`platform:155` 和 `universal:155` 表示两个不同的计划实例。
```http
POST https://api.xunjiapp.cn/open/plan/query_gzip
Authorization: Bearer xjllm_84866d3e3bfefdcbf7b30ef31c172f9e854cebc398b5a1ea
Accept-Encoding: gzip
Content-Type: application/json

{
  "schema_version": "plan_open_api_v1",
  "action": "list"
}
```
```json
{
  "schema_version": "plan_open_api_v1",
  "action": "get",
  "plan_ref": "platform:155",
  "start_date": "2026-07-12",
  "end_date": "2026-08-12",
  "include_movements": true
}
```
- `list` 在 `res.plans` 返回计划摘要；`get` 返回 `res.plan`、`res.date_range` 和 `res.days`。
- `get` 不传日期时默认读取今天前 7 天到后 30 天；自定义日期范围最多 92 天。
- 只需要日历时传 `include_movements: false`。动作会返回中文名和目标组，不返回内部动作 key、rules 或同步元数据。

## 写回
```http
POST https://trains.xunjiapp.cn/api_upsert_trains_for_llm_v2
Authorization: Bearer xjllm_84866d3e3bfefdcbf7b30ef31c172f9e854cebc398b5a1ea
Content-Type: application/json

{
  "schema_version": "train_open_api_v2",
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "include_full_data": false,
  "res": [
    {
      "datestr": "2026-04-02",
      "localid": 123456,
      "title": "胸部训练",
      "start": 1744010000000,
      "end": 1744013600000,
      "movements": [
        { "name": "杠铃卧推", "restTime": 90, "warn_restTime": 45, "sets": [
          { "done": true, "weight": "20", "unit": "kg", "reps": "10", "setType": "热" },
          { "done": true, "weight": "60", "unit": "kg", "reps": "10" }
        ] }
      ]
    }
  ]
}
```

## 新建有氧日
- 新建 CardioPage 原生有氧时，用一个 `cardio: true` 的 movement，不要传 `sets`，指标写在 movement 顶层 `metrics`。
- 不要用 `跑步_有氧训练` + `sets` 新建有氧日；那会变成力量训练里的有氧动作。
- `recordPreset` 可用 `general`、`running`、`walking`、`cycling`、`swimming`、`jumpRope`、`hiit` 等。时长优先用训练 `start/end`，也兼容 movement 的 `workoutTime`/`duration_s`。
```json
{
  "datestr": "2026-04-02",
  "title": "跑步",
  "start": 1744010000000,
  "end": 1744011800000,
  "movements": [
    {
      "name": "跑步",
      "cardio": true,
      "recordPreset": "running",
      "metrics": {
        "distance": "5",
        "pace": "6:00",
        "cadence": "170",
        "kcal": "300",
        "bpm": "140"
      }
    }
  ]
}
```

## RPE 与动作完成难度
- 改 RPE 或动作完成难度前，用 `include_full_data: true` 读取原训练；写回时保留原训练其它动作、组和 note 元数据。
- RPE 写在具体组上：`movements[].sets[].rpe`。合法值用字符串：`"6"`、`"6.5"`、`"7"`、`"7.5"`、`"8"`、`"8.5"`、`"9"`、`"9.5"`、`"10"`；清空 RPE 用 `""`，不要写 `0`。
- 超级组子项的 RPE 写在对应子项的 `sets[].items[].set.rpe`。
- 简单/正常/困难写在动作对象上：`movements[].difficulty`，合法值只用 `easy`、`normal`、`hard`；不要把中文“简单/正常/困难”写进字段。
- 写回涉及 RPE 或 `difficulty` 时，建议请求里传 `include_full_data: true`，方便服务端返回完整标准化数据。
```json
{
  "include_full_data": true,
  "res": [
    {
      "datestr": "2026-04-02",
      "localid": 123456,
      "movements": [
        {
          "name": "杠铃卧推",
          "difficulty": "hard",
          "sets": [
            { "done": true, "weight": "60", "unit": "kg", "reps": "10", "rpe": "8.5" }
          ]
        }
      ]
    }
  ]
}
```

## 历史颜色
- 训练历史卡片颜色存在训练 `note.trainColor`，不是顶层 `color`。
- 改颜色前先读取原训练；写回时保留 `localid`、`datestr`、`start`、`end`、`title`、`movements` 和 `note` 里的其它元数据，只改 `trainColor`。
- 颜色使用 CSS 十六进制字符串，如 `#FF7A00`；清空自定义历史颜色用 `""`。
- 如果 `note` 是 JSON 字符串，先解析成对象，合并 `trainColor` 后再按接口支持的形态写回 `note`；不要覆盖 `text`、`heartRate`、`customTitle`、`personalworkout_*` 等字段。
```json
{
  "localid": 123456,
  "datestr": "2026-04-02",
  "note": {
    "text": "今天状态不错",
    "trainColor": "#FF7A00"
  }
}
```

## 写回规则
- 写回动作只传中文 `name`，不要传 `key`；服务端会按中文名查找并回填内部 key。
- 不确定中文名时，先读取 `https://github.com/Foveluy/Xunji-movements`，只从表里的中文名里选择。
- `res` 可以是训练数组，也可以是 `{ "trains": [...] }`；单次最多 4 条训练，且必须属于同一天。
- 每条训练最多 15 个动作；超级组按各轮最大的子动作数计入该上限。每个动作最多 20 组或轮，不支持嵌套超级组，超过会被服务端拒绝。
- 超级组回写用 `movements[].sets[].items[]`：每个 set 表示一轮，`done` 表示整轮完成；每个 item 包含中文 `name` 和单个 `set` 对象。服务端补齐子动作 key 并转换为 App 结构。修改前读取完整数据，保留所有轮次和子项。
- 超级组动作示例（放入 `movements`）：{"name":"推拉超级组","restTime":90,"sets":[{"done":false,"items":[{"name":"杠铃卧推","set":{"weight":"40","unit":"kg","reps":"10","done":false}},{"name":"引体向上","set":{"reps":"8","selfWeight":true,"done":false}}]}]}。多轮就在 `sets` 中继续添加，勿传内部 `moves` 或 key。
- `movements[].restTime` 设置正式组休息，`movements[].warn_restTime` 设置热身组休息（0～86400 秒）。每个热身组写 `movements[].sets[].setType: "热"`，正式组可省略。`sets[].restSeconds` 仅记录实际已休息时长。
- 原生有氧日用 `cardio: true` 且不传 `sets`；服务端会回填内部有氧 key。
- 有 `localid` 时更新原训练；没有 `localid` 时新建训练；不要因为列表里缺少旧训练就删除旧训练。
- 更新旧训练时保留 `localid`、`start`、`end`，除非用户明确要改时间。
- 组至少包含 `weight`/`weight_kg`、`reps`、`time`/`duration_s`、`selfWeight` 之一。
- 未完成组用 `done: false`；不要把完整模式读到的未完成组擅自删掉。
- 写回成功后，用服务端返回的标准化 `res` 覆盖缓存。

## 限频与错误
- 同一用户同一训练日：默认读取 15 秒一次，`include_full_data: true` 读取 30 秒一次，写回 45 秒一次；`too frequent` 时等待提示的 retry 时间。
- 官方计划的 `list`/`get` 按同一 Key、操作和计划实例 15 秒限频；重试前等待 `retry_after_ms`。
- 不确定动作名时不要编造；让用户确认中文动作名后再写回。
- `apikey missing` / `apikey invalid`: 让用户回 App 重新申请，然后复制并重新发送最新的训练数据 Skill。
- `仅VIP可用`: 当前账号需要会员权限。


---

# 训记饮食数据 Open API Skill

## 原则
- 只在用户明确要求读取、搜索、整理或写回饮食数据时调用接口。
- 写回、创建自定义食物或套用模板前，必须先展示变更摘要，并等待用户确认。
- 按查询条件缓存读取结果；相同条件不要重复请求。
- 查询范围默认限制在过去一年到未来 3 个月。

## 鉴权
- 查询、写回、自定义食物和模板接口请求头: `Authorization: Bearer xjfood_a2355c750676cc1add97de49374eade03c39718e1fb24555`
- 食物搜索接口请求头: `Authorization: Bearer cc610e97a69ebb7a14dc2a472d07f6bc`
- 饮食记录接口也兼容请求头 `x-api-key`；食物搜索接口也兼容 `x-agent-key` 或 `x-api-key`。
- 不支持把 Key 放在 body 或 query 里。
- 不要把 Key 写入日志或展示给第三方。

## 接口
- 饮食记录 Base URL: `https://eatings.xunjiapp.cn`
- 查询饮食记录: `POST /open/food/query_gzip`
- 写回饮食记录: `POST /open/food/upsert_gzip`
- 新增或更新自定义食物: `POST /open/food/custom/upsert_gzip`
- 查询饮食模板: `POST /open/food/templates/list_gzip`
- 套用饮食模板: `POST /open/food/templates/apply_gzip`
- 食物搜索 Base URL: `https://api.xunjiapp.cn`
- 搜索官方食物: `POST /open_agent/food/search_gzip`
- 成功时 `success === true`，核心数据在 `res`。

## 查询饮食记录
```http
POST https://eatings.xunjiapp.cn/open/food/query_gzip
Authorization: Bearer xjfood_a2355c750676cc1add97de49374eade03c39718e1fb24555
Content-Type: application/json

{
  "start_date": "2025-06-12",
  "end_date": "2026-09-12",
  "include_detail": true
}
```

- 查询日期不要早于过去一年，也不要晚于未来 3 个月；用户要求更大范围时先解释限制并拆分到允许范围内。
- 读取后按日期、餐次、食物名称和记录 id 缓存；写回成功后用服务端返回数据覆盖缓存。
- 只读取用户明确需要的日期范围；不要为了模糊问题一次性扫全量。

## 搜索食物
```http
POST https://api.xunjiapp.cn/open_agent/food/search_gzip
Authorization: Bearer cc610e97a69ebb7a14dc2a472d07f6bc
Content-Type: application/json

{
  "keyword": "鸡蛋",
  "limit": 8
}
```

- 搜索接口走主服务器，链路与 App 客户端一致：先按关键词找官方食物 id，再返回训记库里的 `ntr`、`units`、`uniquekey`。
- 优先使用 `res.foods`；其中 `ntr` 是每 100g 营养，`units` 是可选单位换算，`uniquekey` 写回时要带上。
- `res.d` 是客户端同款压缩数组，格式为 `[id, name, cal, carb, fat, protein, foodpic, uniquekey, units]`。
- 不确定食物匹配、单位或份量时先让用户确认；不要只凭相似名称直接写回。
- 搜索不到或用户要记录包装食品、餐厅食物、私有食物时，再通过公开营养信息或用户提供信息创建自定义食物。

## 创建自定义食物
```http
POST https://eatings.xunjiapp.cn/open/food/custom/upsert_gzip
Authorization: Bearer xjfood_a2355c750676cc1add97de49374eade03c39718e1fb24555
Content-Type: application/json

{
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "food": {
    "name": "用户确认的食物名",
    "ntr": {
      "cal": 165,
      "protein": 31,
      "fat": 3.6,
      "carb": 0,
      "foodpic": "",
      "foodUnit": [{ "unit": "份", "count": "1", "gram": 100 }]
    },
    "units": [{ "unit": "份", "count": "1", "gram": 100 }]
  }
}
```

- 只有搜索不到合适官方食物，或用户明确要创建私有食物时，才创建自定义食物。
- 需要新食物时，agent 应自行通过公开网页、包装营养成分表或用户提供信息查找每 100g 营养。
- 创建前必须向用户展示营养来源和摘要，并让用户确认食物名、每 100g 热量、蛋白质、脂肪、碳水；不确定时追问，不要估算。
- `ntr` 按训记格式写入：`cal`、`protein`、`fat`、`carb` 都是每 100g 数值；可带 `foodpic`。
- `units` 和 `ntr.foodUnit` 必须一致；没有明确份量单位时传空数组，默认按克记录。
- 创建成功后，使用返回的 `res.food` 里的 `name`、`uniquekey`、`unit/units`、`ntr` 再调用写回饮食记录。

## 写回饮食记录
```http
POST https://eatings.xunjiapp.cn/open/food/upsert_gzip
Authorization: Bearer xjfood_a2355c750676cc1add97de49374eade03c39718e1fb24555
Content-Type: application/json

{
  "client_request_id": "unique-id-from-agent",
  "dry_run": false,
  "foods": [
    {
      "date": "2026-06-12",
      "meal_type": "lunch",
      "name": "鸡胸肉",
      "amount": 150,
      "unit": "g",
      "uniquekey": "使用搜索结果或自定义食物返回的 uniquekey",
      "ntr": { "cal": 165, "protein": 31, "fat": 3.6, "carb": 0 }
    }
  ]
}
```

- 官方食物写回前先调用搜索接口，优先带上搜索结果里的 `uniquekey`、`units` 和 `ntr`。
- 写回前必须已经有用户确认过的 `ntr`；写回接口不会搜索食物或替你猜营养。
- 如果需要新增食物，先自行查找公开营养信息并创建自定义食物，再用创建接口返回的 `res.food` 作为写回来源。

## 自定义食物与模板
- 新增或更新自定义食物使用 `POST /open/food/custom/upsert_gzip`。
- 查询模板使用 `POST /open/food/templates/list_gzip`。
- 套用模板使用 `POST /open/food/templates/apply_gzip`。
- 创建自定义食物或套用模板也属于写回操作，必须先给用户看摘要并等待确认。

## 写回规则
- 写回前先展示将新增、修改或覆盖的日期、餐次、食物、数量和单位。
- 用户确认后再调用写回、自定义食物或模板套用接口。
- 有服务端记录 id 时更新原记录；没有 id 时新建记录。
- 不要因为查询结果里缺少旧记录就删除旧记录，除非用户明确要求删除。
- 不确定餐次、数量、单位或食物匹配时先追问用户。

## 限频与错误
- 饮食记录同一用户同类接口 15 秒一次；食物搜索接口同样 15 秒一次；`too frequent` 时等待提示的 retry 时间。
- `apikey missing` / `apikey invalid`: 让用户回 App 重新申请，然后复制并重新发送最新的饮食数据 Skill。
- `仅VIP可用`: 当前账号需要会员权限。


---

# 训记身体数据 Open API Skill

## 原则
- 只在用户明确要求读取、导出、总结、对比、记录或更新身体数据时调用接口。
- 写入身体数据前，必须先给用户展示清晰的变更摘要，包括日期、指标类型、数值和单位，并等待用户明确确认。
- 用户确认前不要发送 `confirmed: true`。不要根据推测或未确认建议直接写入身体数据。
- 按日期范围和类型缓存读取结果；相同查询不要重复请求。
- 身体指标属于个人健康数据，分析趋势时保持谨慎，不做医疗诊断。

## 鉴权
- 请求头: `Authorization: Bearer xjbody_fc09cf92468552bbe40266b48c61e9c2ad999bbf5f969fd0`
- 也兼容请求头 `x-api-key`。
- 不支持把 Key 放在 body 或 query 里。
- 不要把 Key 写入日志或展示给第三方。

## 接口
- Base URL: `https://api.xunjiapp.cn`
- 查询身体数据: `POST /open/body/query_gzip`
- 写入身体数据: `POST /open/body/upsert_gzip`
- 成功时 `success === true`，核心数据在 `res`。

## 查询
```http
POST https://api.xunjiapp.cn/open/body/query_gzip
Authorization: Bearer xjbody_fc09cf92468552bbe40266b48c61e9c2ad999bbf5f969fd0
Content-Type: application/json

{
  "start_date": "2026-01-01",
  "end_date": "2026-06-28",
  "types": ["weight", "bodyfat"],
  "include_latest": true,
  "include_records": true,
  "limit": 500,
  "offset": 0
}
```

- 不传 `types` 时读取全部身体指标。只看体重用 `types: ["weight"]`，只看体脂率用 `types: ["bodyfat"]`。
- `records[]` 按日期倒序返回；每条有 `datestr`、`type`、`value`、`unit`、`label`、`label_en`。
- `latest` 是每个类型的最新记录；`by_type` 按类型归组本次返回的记录。
- `value` 会尽量转成数字。单位：`weight` 是 kg，`bodyfat` 是 %，围度/身体尺寸是 cm。

## 写入
- 写入按 `datestr + type` upsert：已有记录会更新，没有记录会新建。
- 先用 `dry_run: true` 校验；把 `res.summary` 展示给用户，并请用户确认。
- 只有用户确认后，才用相同记录再次请求 `dry_run: false` 和 `confirmed: true`。
- 真正写入必须带 `confirmed: true`；缺少时服务端会返回 `user confirmation required`。
```http
POST https://api.xunjiapp.cn/open/body/upsert_gzip
Authorization: Bearer xjbody_fc09cf92468552bbe40266b48c61e9c2ad999bbf5f969fd0
Content-Type: application/json

{
  "schema_version": "body_open_api_v1",
  "client_request_id": "unique-id-from-agent",
  "dry_run": true,
  "records": [
    { "datestr": "2026-06-28", "type": "weight", "value": 72.4 },
    { "datestr": "2026-06-28", "type": "bodyfat", "value": 18.2 }
  ]
}
```
```json
{
  "dry_run": false,
  "confirmed": true,
  "records": [
    { "datestr": "2026-06-28", "type": "weight", "value": 72.4 }
  ]
}
```

## 身体数据类型
- `weight`: 体重，单位 kg。
- `bodyfat`: 体脂率，单位 %。
- `neck`、`chest`、`weist`、`shoulder`、`bot`: 脖围、胸围、腰围、肩宽、臀围，单位 cm。腰围字段历史拼写是 `weist`，不要改成 `waist`。
- `arm_left`、`arm_right`、`forearm_left`、`forearm_right`、`leg_left`、`leg_right`、`cav_left`、`cav_right`: 左/右臂围、小臂围、腿围、小腿围，单位 cm。

## 限频与错误
- 身体数据查询和写入接口，同一 key 同一 endpoint 15 秒一次；`too frequent` 时等待 `retry_after_ms`。
- `apikey missing` / `apikey invalid`: 让用户回 App 重新申请，然后复制并重新发送最新的身体数据 Skill。
- `user confirmation required`: 先展示写入摘要给用户，等用户确认后再带 `confirmed: true` 重试。
- `仅VIP可用`: 当前账号需要会员权限。


---

# 训记 Agent 个人模版 Skill

## 用途
- 只管理用户现有个人模版系统里的「Agent 模版」专属文件夹。
- 写入后的模版会直接出现在训记，可像普通个人模版一样开始训练、排期、复制或编辑。
- 用户明确确认后，Agent 可以自定义专属文件夹的显示名称；不得改变文件夹 ID、移动、分享或删除它。
- 用户只能在训记 App 内删除这个专属文件夹；该操作会同时删除内部全部模版。获取到 `folder_deleted` 后不得自行重建，除非用户之后明确要求新建 Agent 模版。

## 硬性容量限制
- Agent 只允许使用 1 个服务端 ID 固定、显示名称可自定义的专属文件夹；不得创建、请求或模拟第二个文件夹或子文件夹。
- 这个文件夹最多保存 14 个有效模版；更新已有模版不额外占用名额。
- 每个模版最多 15 个动作。
- 每个动作最多 20 组。
- 写入前必须检查全部四项限制。超限时应询问用户删减或替换哪项；不得静默截断、另建文件夹拆分，也不得未经确认删除已有模版。
- 14 个名额已满时，可以在同一次明确确认的 mutation 中删除 1 个旧模版并新建 1 个模版。

## 鉴权
- Base URL：`https://trains.xunjiapp.cn`
- Header：`Authorization: Bearer xjtpl_07aa2ade8a8af9b49c255fb073d638b27476352efd462bbf`
- 本 Skill 使用独立的个人模版 Key。不得把 Key 放进 query/body、日志或展示给第三方。
- 同步和写入成功响应统一使用 gzip level 6；常见 HTTP 客户端会自动解压。

## 实时获取（v2）
- 接口：`POST /api_agent_templates_sync_for_llm_v2`
- 发送 `{}` 即可一次获取当前全部模版，不需要游标、分页或持久化同步状态。
- 有完整本地缓存时可传 `template_versions: { "模版ID": 3 }`，只返回版本不同的内容；内容缺失的模版不要报版本。
- 每次返回最新 `folder`、`limits` 和完整 `template_versions` 清单；`templates` 只包含新增或版本不同的完整模版。
- 替换变化的缓存模版，保留同版本内容；按 `deleted_template_ids` 清理该 Agent 文件夹缓存，不得删除已移到其他文件夹的模版。
- `folder_deleted: true` 且 `folder: null` 表示文件夹不存在或已删除，清理其缓存，不得自动重建。
- 每次读取或编辑模版前获取一次；写入成功后需要最新状态时再获取。不需要保存或回放变更日志。
- App 在模版界面启用自动刷新，用户不需要维护同步游标或手动点刷新。
```http
POST https://trains.xunjiapp.cn/api_agent_templates_sync_for_llm_v2
Authorization: Bearer xjtpl_07aa2ade8a8af9b49c255fb073d638b27476352efd462bbf
Accept-Encoding: gzip
Content-Type: application/json

{ "template_versions": {} }
```

## 新建或更新模版
- 接口：`POST /api_agent_templates_mutate_for_llm_v1`
- 每次写入前，先向用户展示准确的文件夹改名和/或模版名、动作、组数、递增规则变更，等待明确确认。
- 确认后发送 `confirmed: true`，并使用重试时保持不变的唯一 `mutation_id`。
- 相关修改合并成一次请求（最多 14 个 upsert + 14 个 delete），减少流量。
- 新建时发送稳定 `client_id`，服务端据此生成幂等的模版 ID。
- 更新/删除时发送同步所得的 `template_id` 与最新 `base_version`。遇到 `version conflict`，先重新同步、展示冲突，再询问用户。
- 修改唯一文件夹名称时，发送 `folder_update: { name, base_version }`，版本取自同步所得的 folder。规范化后的名称不能为空且最多 32 个字符；不改名时省略 `folder_update`。
- 文件夹名和模版名只能包含中文、英文字母、数字和普通空格；禁止 emoji、标点、符号、换行、零宽/不可见字符和双向覆盖字符。
- Agent 写入的所有可见文本都会在训记服务器本地执行内容安全检查，不会发送给第三方审核服务。
- 文件夹改名可以是一次 mutation 的唯一操作，但仍必须带 `confirmed: true` 和唯一 `mutation_id`。
- 成功后用规范化的 `applied[].data` 更新缓存并应用返回的删除项，或重新获取 v2；忽略旧 `next_cursor`；相同 `mutation_id` 的重试会返回相同结果。
- 新建优先使用公开 `movements` 结构；编辑已有模版时，可把同步返回的原生 `movement` 和 `rules` 按需修改后原样写回。
```json
{
  "confirmed": true,
  "mutation_id": "agent-request-unique-id",
  "folder_update": { "name": "我的增肌模版", "base_version": 1 },
  "upserts": [{
    "client_id": "push-a-v1",
    "name": "推 A",
    "color": "#FF8A1F",
    "movements": [{
      "name": "杠铃卧推",
      "sets": [{ "weight": 60, "reps": 8, "unit": "kg" }],
      "progression": {
        "start_reps": 8, "reps_increment": 1, "target_reps": 12,
        "weight_increment": 2.5, "reset_reps": 8
      }
    }]
  }],
  "deletes": []
}
```

## 规则与安全
- 公开结构里的动作名必须使用训记官方中文名；动作、单位、组次或递增规则不确定时先问用户。
- 双重递增：先增加次数；所有工作组达到目标次数后再增加重量并重置次数。不要编造百分比或进度分。
- 绝不修改 Agent 文件夹之外的个人模版。
- `folder_name invalid` / `folder_base_version invalid`：询问一个非空且最多 32 个字符的名称，并使用最新同步得到的文件夹版本。
- `folder_name special characters not allowed` / `name special characters not allowed`：请用户改用仅包含中文、英文字母、数字和空格的名称；不得使用相似字形或不可见字符绕过。
- `content safety rejected`：说明文本未通过训记本地内容安全规则，请用户提供安全替代文案；不得混淆文字后自动重试。
- `template limit exceeded (max 14)`：重新同步并展示当前 14 个模版，询问用户替换或删除哪一个。
- `movements invalid` / `sets invalid`：把请求调整到每个模版最多 15 个动作、每个动作最多 20 组；不得静默截断。
- `user confirmation required`：先展示摘要，等用户确认，再带 `confirmed: true` 重试。
- `too frequent`：按提示等待，不要循环请求。
- `apikey missing` / `apikey invalid`：让用户回 App 重新申请，再复制并发送最新 Skill。
