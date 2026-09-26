# 联赛递归排名（League Board）

无持久化的联赛排名系统：Vue 页面编辑比分，派单时携带递增 `request_id`，Python/Flask
接口执行“总积分 → 递归相互战绩 → 全局净胜球/进球/ASCII 字节序”的排名。所有状态只存在
于请求与浏览器中，服务端不落盘。

## 排名规则

1. 胜 3 分、平 1 分、负 0 分，先按**总积分**分组。
2. 每个并列组只统计**当前组内球队之间已赛比赛**的积分并拆分。
3. 拆出后仍并列的子组**重新计算**该子组内的相互战绩（不沿用上一组的积分）。
4. 某组无法再拆分时，依次比较：
   1. 全局净胜球；
   2. 全局进球数；
   3. 球队 id 的 ASCII 字节序（保证结果确定且与输入顺序无关）。

接口返回完整名次 `standings`，以及每次分组的依据 `tiebreakers`（参与球队、
组内积分/净胜球数值、拆分结果与递归深度）。

## 截至轮次排名

申诉受理后，领队需要查看任一轮结束时**真实生效**的名次，而不能把今天的
处罚倒灌进过去的榜单。独立接口 `POST /api/rankings/as-of-round` 与原排名
接口互不影响：

- 每场比赛携带正整数 `round`；只有 `round <= as_of_round` 的已赛比赛参与
  计算，之后的比赛与事件对该视图完全不可见。
- 每条处罚含唯一 `id`、`team`、`effective_round` 与正整数 `deduction`。
- 一次申诉（`appeals`）只能引用一条既有处罚，`effective_round` 不得早于
  该处罚，并从该轮起撤销其扣分；同一生效轮次即表示该扣分从未生效。
- 一条处罚至多被一次申诉引用；非法引用、重复申诉、无效轮次或未知球队都会
  让整份请求返回 400，不产生任何部分结果。

根分组先按“比赛积分 − 当前有效扣分”形成**调整后总积分**分组；组内相互
战绩仍只由已赛比赛积分计算（扣分不进入相互战绩），递归拆组与全局净胜球、
全局进球、ASCII 字节序裁决完全沿用原规则。响应的 `standings` 同时给出
每队 `match_points`（比赛积分）、`deductions`（有效扣分）、
`active_penalties`（仍在生效的处罚编号与扣分值）、`adjusted_points`
（调整后积分）以及逐级排名依据 `tiebreakers`。

```bash
curl -X POST http://localhost:8000/api/rankings/as-of-round \
  -H 'Content-Type: application/json' \
  -d '{
        "request_id": 1,
        "teams": ["A", "B", "C", "D"],
        "matches": [
          {"home": "A", "away": "C", "home_score": 1, "away_score": 0, "round": 1},
          {"home": "A", "away": "B", "home_score": 0, "away_score": 0, "round": 2}
        ],
        "penalties": [
          {"id": "P1", "team": "A", "effective_round": 2, "deduction": 1}
        ],
        "appeals": [
          {"penalty_id": "P1", "effective_round": 3}
        ],
        "as_of_round": 2
      }'
```

页面上“当前排名”与“截至轮次排名”是两个独立流程：切换轮次或编辑比赛/
处罚事件会让旧榜单与旧解释立即失效；每个流程用各自的 `request_id`、
编辑序号与轮次序号校验响应，迟到的旧轮次响应不会覆盖新轮次视图。

## 输入约束

- 4–12 支球队；id 为 1–40 个可打印 ASCII 字符且唯一；
- 每对球队至多一场比赛；
- 比分为 0–20 的整数；未提交的比赛视为尚未进行；
- 可携带非负整数 `request_id`，接口原样回显，页面据此只展示当前请求版本的解释。

## 目录

```
backend/    Flask 接口与 pytest（排名规则 + 一条 Playwright 主流程）
frontend/   Vue 3 + Vite 页面（生产镜像用 nginx 托管并代理 /api）
docker-compose.yml   分别启动 standings(8000) 与 board(8080)
```

## 用 Compose 启动

```bash
docker compose up --build
# 积分榜页面： http://localhost:8080
# 排名接口：    http://localhost:8000/api/rankings
```

接口示例：

```bash
curl -X POST http://localhost:8000/api/rankings \
  -H 'Content-Type: application/json' \
  -d '{
        "request_id": 1,
        "teams": ["A", "B", "C", "D"],
        "matches": [
          {"home": "A", "away": "B", "home_score": 2, "away_score": 1}
        ]
      }'
```

## 本地开发与测试

后端：

```bash
cd backend
pip install -r requirements.txt
flask --app app.api run --port 8000
pytest                       # 排名规则与接口测试
```

前端：

```bash
cd frontend
npm install
npm run dev                  # 默认把 /api 代理到 http://localhost:8000
```

浏览器主流程（需先启动页面与接口，再安装 Playwright 的 Chromium）：

```bash
python -m playwright install chromium
BOARD_URL=http://localhost:8080 pytest -m browser
```

该用例覆盖页面主流程：计算并显示名次与分组解释 → 修改比分后旧版本解释立即
消失 → 重新计算后只显示新 `request_id` 对应的解释；以及截至轮次流程的
扣分改变并列组、申诉恢复（含同轮生效）、切换轮次旧解释立即失效与乱序响应
丢弃。Chromium 缺失时该用例自动跳过，其余规则测试不受影响。

## 版本一致性

当前排名页面维护两个计数器：`requestSeq` 作为请求 id 发送并由接口回显；
`editSeq` 在每次编辑时递增。响应返回时两者都必须与发起请求时一致才会
渲染，因此迟到的旧响应或编辑前发出的响应都不会覆盖当前页面。

截至轮次流程额外维护 `roundSeq`（每次切换截至轮次时递增）：响应必须同时
匹配请求 id、编辑序号与轮次序号才会渲染，因此旧轮次的迟到响应或编辑前
发出的响应都不会覆盖新轮次页面。服务端无状态，两份流程互不影响。
