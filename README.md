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

## 截至轮次排名（纪律处罚与申诉）

`POST /api/rankings/at-round` 是独立流程：领队查看**任一轮结束时真实生效**的名次，
今天的处罚不会倒灌进过去的榜单。

- 每场比赛携带 `round`（≥1 的整数）；只统计**所选轮次及之前**的比赛。
- 处罚 `penalties`：`id`（唯一编号）、`team`、`round`（生效轮次）、`points`
  （扣分值，≥1 的整数），从生效轮次起扣分。
- 申诉 `appeals`：一次申诉只引用**一条既有处罚**（`penalty_id`），`round`
  不得早于处罚轮次，从该轮起撤销该处罚的扣分；同一处罚不能被重复申诉。
- 所选轮次之后的比赛、处罚与申诉一律不参与计算。
- 分组规则不变：比赛积分加当前有效扣分形成总积分分组；组内相互战绩仍只由
  已赛比赛计算；递归拆组与全局净胜球/进球/ASCII 裁决沿用原规则。
- 非法引用、重复申诉、无效轮次等任何问题都会**整份拒绝**（400）。

响应中每队给出 `match_points`（比赛积分）、`deduction`（当前有效扣分）、
`points`（调整后积分）以及 `tiebreakers` 逐级排名依据（深度 0 的分组事件同样
携带三值明细），并回显 `request_id` 与 `round`。

```bash
curl -X POST http://localhost:8000/api/rankings/at-round \
  -H 'Content-Type: application/json' \
  -d '{
        "request_id": 1,
        "round": 2,
        "teams": ["A", "B", "C", "D"],
        "matches": [
          {"home": "A", "away": "B", "home_score": 2, "away_score": 1, "round": 1}
        ],
        "penalties": [{"id": "P1", "team": "B", "round": 2, "points": 3}],
        "appeals": [{"penalty_id": "P1", "round": 3}]
      }'
```

原 `POST /api/rankings` 接口保持不变。

## 输入约束

- 4–12 支球队；id 为 1–40 个可打印 ASCII 字符且唯一；
- 每对球队至多一场比赛；
- 比分为 0–20 的整数；未提交的比赛视为尚未进行；
- 可携带非负整数 `request_id`，接口原样回显，页面据此只展示当前请求版本的解释。

## 目录

```
backend/    Flask 接口与 pytest（排名规则、截至轮次流程 + Playwright 主流程）
frontend/   Vue 3 + Vite 页面（生产镜像用 nginx 托管并代理 /api）
docker-compose.yml   分别启动 standings(8000) 与 board(8080)
```

## 用 Compose 启动

```bash
docker compose up --build
# 积分榜页面： http://localhost:8080
# 排名接口：    http://localhost:8000/api/rankings
# 截至轮次：    http://localhost:8000/api/rankings/at-round
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
pytest                       # 排名规则、截至轮次流程与接口测试
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

浏览器用例覆盖两条主流程：

- 原流程：计算并显示名次与分组解释 → 修改比分后旧版本解释立即消失 → 重新计算后
  只显示新 `request_id` 对应的解释。
- 截至轮次流程：扣分改变并列组 → 申诉同轮生效并恢复积分 → 切换轮次旧解释立即
  失效 → 拦截接口制造乱序响应，迟到的旧轮次响应不得覆盖新轮次。

Chromium 缺失时这些用例自动跳过，其余规则测试不受影响。

## 版本一致性

页面维护三个计数器：`requestSeq` / `roundRequestSeq` 分别作为两条流程的请求 id
发送并由接口回显；`editSeq` 在每次编辑（比分、轮次、处罚、申诉、截至轮次）时递增。
响应返回时请求 id 与 `editSeq` 都必须与发起请求时一致才会渲染，因此迟到的旧响应
或编辑前发出的响应都不会覆盖当前页面。
