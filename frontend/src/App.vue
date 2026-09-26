<script setup>
import { computed, reactive, ref } from 'vue'

let uidCounter = 0
const nextUid = () => `row-${++uidCounter}`

function makeMatch(a, b, played = false, homeScore = null, awayScore = null, round = 1) {
  return { a, b, played, homeScore, awayScore, round }
}

function initialState() {
  const teams = ['A', 'B', 'C', 'D'].map((id) => ({ uid: nextUid(), id }))
  // Pairs are generated with teams in index order, so keys are i<j.
  const initialScores = {
    AB: [1, 0],
    AC: [0, 1],
    AD: [1, 0],
    BC: [1, 0],
    BD: [1, 0],
    CD: [1, 0]
  }
  const initialRounds = { AB: 1, AC: 2, AD: 3, BC: 3, BD: 2, CD: 1 }
  const matches = []
  for (let i = 0; i < teams.length; i += 1) {
    for (let j = i + 1; j < teams.length; j += 1) {
      const a = teams[i].uid
      const b = teams[j].uid
      const key = teams[i].id + teams[j].id
      const [hs, as] = initialScores[key] ?? [null, null]
      matches.push(makeMatch(a, b, key in initialScores, hs, as, initialRounds[key] ?? 1))
    }
  }
  return { teams, matches }
}

const seed = reactive(initialState())
const teams = seed.teams
const matches = seed.matches

// Disciplinary events for the as-of-round flow.
const penalties = reactive([])
const appeals = reactive([])
const selectedRound = ref(1)
let penaltySeq = 0

const teamById = computed(() => {
  const map = new Map()
  teams.forEach((team) => map.set(team.uid, team))
  return map
})

const loading = ref(false)
const errorMessage = ref('')
const result = ref(null)
const roundLoading = ref(false)
const roundError = ref('')
const roundResult = ref(null)
// requestSeq / roundRequestSeq identify a particular request and are echoed
// by the API; editSeq is bumped by every form edit so a response that was
// in flight before the edit can never populate the page again.
const requestSeq = ref(0)
const roundRequestSeq = ref(0)
const editSeq = ref(0)

function markDirty() {
  editSeq.value += 1
  result.value = null
  errorMessage.value = ''
  loading.value = false
  roundResult.value = null
  roundError.value = ''
  roundLoading.value = false
}

function addTeam() {
  if (teams.length >= 12) return
  const team = { uid: nextUid(), id: String.fromCharCode(65 + teams.length) }
  teams.forEach((existing) => {
    matches.push(makeMatch(existing.uid, team.uid))
  })
  teams.push(team)
  markDirty()
}

function removeTeam(uid) {
  if (teams.length <= 4) return
  const index = teams.findIndex((team) => team.uid === uid)
  teams.splice(index, 1)
  for (let i = matches.length - 1; i >= 0; i -= 1) {
    if (matches[i].a === uid || matches[i].b === uid) matches.splice(i, 1)
  }
  // Disciplinary events tied to the removed team disappear as well.
  const removedPenaltyUids = new Set()
  for (let i = penalties.length - 1; i >= 0; i -= 1) {
    if (penalties[i].teamUid === uid) {
      removedPenaltyUids.add(penalties[i].uid)
      penalties.splice(i, 1)
    }
  }
  for (let i = appeals.length - 1; i >= 0; i -= 1) {
    if (removedPenaltyUids.has(appeals[i].penaltyUid)) appeals.splice(i, 1)
  }
  markDirty()
}

function addPenalty() {
  penaltySeq += 1
  penalties.push({
    uid: nextUid(),
    id: `P${penaltySeq}`,
    teamUid: teams[0]?.uid ?? '',
    round: 1,
    points: 1
  })
  markDirty()
}

function removePenalty(uid) {
  const index = penalties.findIndex((penalty) => penalty.uid === uid)
  if (index === -1) return
  penalties.splice(index, 1)
  // Appeals of a removed penalty have nothing to reference anymore.
  for (let i = appeals.length - 1; i >= 0; i -= 1) {
    if (appeals[i].penaltyUid === uid) appeals.splice(i, 1)
  }
  markDirty()
}

function addAppeal() {
  if (!penalties.length) return
  appeals.push({ uid: nextUid(), penaltyUid: penalties[0].uid, round: 1 })
  markDirty()
}

function removeAppeal(uid) {
  const index = appeals.findIndex((appeal) => appeal.uid === uid)
  if (index === -1) return
  appeals.splice(index, 1)
  markDirty()
}

function payloadError() {
  const ids = teams.map((team) => team.id)
  if (ids.some((id) => !/^[\x21-\x7E]{1,40}$/.test(id))) {
    return '球队 id 必须是 1 至 40 个非空白 ASCII 字符。'
  }
  if (new Set(ids).size !== ids.length) return '球队 id 必须唯一。'
  const badScore = matches.some(
    (match) =>
      match.played &&
      (!Number.isInteger(match.homeScore) ||
        !Number.isInteger(match.awayScore) ||
        match.homeScore < 0 ||
        match.homeScore > 20 ||
        match.awayScore < 0 ||
        match.awayScore > 20)
  )
  if (badScore) return '已赛比分必须是 0 至 20 的整数。'
  return ''
}

function roundPayloadError() {
  const baseError = payloadError()
  if (baseError) return baseError
  if (!Number.isInteger(selectedRound.value) || selectedRound.value < 1) {
    return '截至轮次必须是大于等于 1 的整数。'
  }
  const badMatchRound = matches.some(
    (match) => match.played && (!Number.isInteger(match.round) || match.round < 1)
  )
  if (badMatchRound) return '已赛比赛的轮次必须是大于等于 1 的整数。'
  const penaltyIds = penalties.map((penalty) => penalty.id)
  if (penaltyIds.some((id) => !/^[\x21-\x7E]{1,40}$/.test(id))) {
    return '处罚编号必须是 1 至 40 个非空白 ASCII 字符。'
  }
  if (new Set(penaltyIds).size !== penaltyIds.length) return '处罚编号必须唯一。'
  if (penalties.some((penalty) => !Number.isInteger(penalty.round) || penalty.round < 1)) {
    return '处罚轮次必须是大于等于 1 的整数。'
  }
  if (penalties.some((penalty) => !Number.isInteger(penalty.points) || penalty.points < 1)) {
    return '处罚扣分必须是大于等于 1 的整数。'
  }
  const appealed = new Set()
  for (const appeal of appeals) {
    const penalty = penalties.find((item) => item.uid === appeal.penaltyUid)
    if (!penalty) return '每次申诉必须引用一条既有处罚。'
    if (appealed.has(appeal.penaltyUid)) return '同一条处罚不能被重复申诉。'
    appealed.add(appeal.penaltyUid)
    if (!Number.isInteger(appeal.round) || appeal.round < 1) {
      return '申诉轮次必须是大于等于 1 的整数。'
    }
    if (appeal.round < penalty.round) return '申诉生效轮次不得早于处罚轮次。'
  }
  return ''
}

async function calculate() {
  const error = payloadError()
  if (error) {
    errorMessage.value = error
    result.value = null
    return
  }

  requestSeq.value += 1
  const requestId = requestSeq.value
  const editAtRequest = editSeq.value
  loading.value = true
  errorMessage.value = ''

  try {
    const response = await fetch('/api/rankings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        teams: teams.map((team) => team.id),
        matches: matches
          .filter((match) => match.played)
          .map((match) => ({
            home: teamById.value.get(match.a).id,
            away: teamById.value.get(match.b).id,
            home_score: match.homeScore,
            away_score: match.awayScore
          }))
      })
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '排名接口返回错误')
    // Reject responses from a different request or from before an edit.
    if (data.request_id !== requestId || editSeq.value !== editAtRequest) return
    result.value = data
  } catch (error) {
    if (requestId === requestSeq.value && editSeq.value === editAtRequest) {
      errorMessage.value = error.message
    }
  } finally {
    if (requestId === requestSeq.value && editSeq.value === editAtRequest) {
      loading.value = false
    }
  }
}

async function calculateAtRound() {
  const error = roundPayloadError()
  if (error) {
    roundError.value = error
    roundResult.value = null
    return
  }

  roundRequestSeq.value += 1
  const requestId = roundRequestSeq.value
  const editAtRequest = editSeq.value
  roundLoading.value = true
  roundError.value = ''

  try {
    const response = await fetch('/api/rankings/at-round', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        round: selectedRound.value,
        teams: teams.map((team) => team.id),
        matches: matches
          .filter((match) => match.played)
          .map((match) => ({
            home: teamById.value.get(match.a).id,
            away: teamById.value.get(match.b).id,
            home_score: match.homeScore,
            away_score: match.awayScore,
            round: match.round
          })),
        penalties: penalties.map((penalty) => ({
          id: penalty.id,
          team: teamById.value.get(penalty.teamUid)?.id ?? '',
          round: penalty.round,
          points: penalty.points
        })),
        appeals: appeals.map((appeal) => ({
          penalty_id:
            penalties.find((penalty) => penalty.uid === appeal.penaltyUid)?.id ?? '',
          round: appeal.round
        }))
      })
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '排名接口返回错误')
    // A response from another request or from before an edit is stale and
    // must never overwrite the round the user is looking at now.
    if (data.request_id !== requestId || editSeq.value !== editAtRequest) return
    roundResult.value = data
  } catch (error) {
    if (requestId === roundRequestSeq.value && editSeq.value === editAtRequest) {
      roundError.value = error.message
    }
  } finally {
    if (requestId === roundRequestSeq.value && editSeq.value === editAtRequest) {
      roundLoading.value = false
    }
  }
}

function teamLabel(uid) {
  return teamById.value.get(uid)?.id ?? '?'
}

function pointRows(event) {
  const source = event.head_to_head_points || event.points || {}
  return Object.values(source).sort((a, b) => a.id.localeCompare(b.id))
}

function tieRows(event) {
  return event.values ? Object.values(event.values).sort((a, b) => a.id.localeCompare(b.id)) : []
}

const basisLabel = {
  total_points: '总积分并列组',
  head_to_head_points: '按当前并列组内比赛积分拆分；剩余子组会重新计算',
  global_tiebreakers: '无法继续拆分，按全局净胜球 → 全局进球 → 球队 id ASCII 字节序'
}
</script>

<template>
  <main class="page">
    <header>
      <p class="eyebrow">无持久化排名服务</p>
      <h1>联赛积分与递归相互战绩</h1>
      <p class="intro">
        先按总积分分组；并列时只统计当前组内比赛，拆出的子组重新计算相互战绩。
        若仍无法拆分，再统一使用全局净胜球、全局进球和 ASCII 字节序。
        “截至轮次排名”在此基础上叠加纪律处罚与申诉：比赛积分加当前有效扣分形成
        总积分，所选轮次之后的比赛与事件一律不参与。
      </p>
    </header>

    <section class="card" data-testid="teams-card">
      <div class="card-title">
        <h2>球队（4–12 支，唯一 ASCII id）</h2>
        <button type="button" :disabled="teams.length >= 12" @click="addTeam">添加球队</button>
      </div>
      <div class="teams">
        <div v-for="team in teams" :key="team.uid" class="team-row">
          <input
            v-model="team.id"
            :aria-label="`球队 ${team.id}`"
            maxlength="40"
            @input="markDirty"
          />
          <button
            type="button"
            class="secondary"
            :disabled="teams.length <= 4"
            @click="removeTeam(team.uid)"
          >
            删除
          </button>
        </div>
      </div>
    </section>

    <section class="card" data-testid="matches-card">
      <div class="card-title">
        <h2>已赛比分</h2>
        <p>每对球队至多一场；未勾选表示尚未比赛。轮次仅用于“截至轮次排名”。</p>
      </div>
      <div class="matches">
        <div v-for="match in matches" :key="match.a + '-' + match.b" class="match-row">
          <label>
            <input type="checkbox" v-model="match.played" @change="markDirty" />
            <span>{{ teamLabel(match.a) }}</span>
          </label>
          <input
            class="score"
            type="number"
            min="0"
            max="20"
            step="1"
            :disabled="!match.played"
            v-model.number="match.homeScore"
            aria-label="主队比分"
            @input="markDirty"
          />
          <span>:</span>
          <input
            class="score"
            type="number"
            min="0"
            max="20"
            step="1"
            :disabled="!match.played"
            v-model.number="match.awayScore"
            aria-label="客队比分"
            @input="markDirty"
          />
          <span>{{ teamLabel(match.b) }}</span>
          <input
            class="round"
            type="number"
            min="1"
            step="1"
            :disabled="!match.played"
            v-model.number="match.round"
            aria-label="比赛轮次"
            title="轮次"
            @input="markDirty"
          />
        </div>
      </div>
    </section>

    <div class="actions">
      <button type="button" class="primary" :disabled="loading" @click="calculate">
        {{ loading ? '计算中…' : '计算名次' }}
      </button>
      <p v-if="errorMessage" class="error" data-testid="error">{{ errorMessage }}</p>
    </div>

    <section v-if="result" class="card" data-testid="standings-card">
      <div class="card-title">
        <h2>完整名次</h2>
        <span class="version" data-testid="result-version">
          当前请求版本：{{ result.request_id }}
        </span>
      </div>
      <table data-testid="standings-table">
        <thead>
          <tr>
            <th>名次</th>
            <th>球队</th>
            <th>积分</th>
            <th>场次</th>
            <th>进球</th>
            <th>失球</th>
            <th>净胜球</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in result.standings" :key="row.team">
            <td>{{ row.rank }}</td>
            <td>{{ row.team }}</td>
            <td>{{ row.points }}</td>
            <td>{{ row.played }}</td>
            <td>{{ row.goals_for }}</td>
            <td>{{ row.goals_against }}</td>
            <td>{{ row.goal_difference }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="result && result.tiebreakers.length" class="card" data-testid="trace-card">
      <h2>每次分组的依据</h2>
      <ol class="trace-list">
        <li v-for="(event, index) in result.tiebreakers" :key="index" class="trace-event">
          <p class="trace-basis">
            <strong>{{ basisLabel[event.basis] }}</strong>
            <span>深度 {{ event.depth }} · 球队：{{ event.teams.join(', ') }}</span>
          </p>

          <table v-if="event.basis !== 'global_tiebreakers'" class="mini-table">
            <thead>
              <tr><th>球队</th><th>{{ event.depth === 0 ? '总积分' : '组内积分' }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in pointRows(event)" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.points }}</td>
              </tr>
            </tbody>
          </table>

          <table v-else class="mini-table">
            <thead>
              <tr><th>球队</th><th>净胜球</th><th>进球</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in tieRows(event)" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.goal_difference }}</td>
                <td>{{ row.goals_for }}</td>
              </tr>
            </tbody>
          </table>

          <div class="partitions">
            <span v-for="(part, partIndex) in event.partitions" :key="partIndex" class="partition">
              {{ part.join(' = ') }}
            </span>
          </div>
        </li>
      </ol>
    </section>

    <section class="card" data-testid="penalties-card">
      <div class="card-title">
        <h2>纪律处罚</h2>
        <button type="button" @click="addPenalty">添加处罚</button>
      </div>
      <p class="hint">每条处罚含唯一编号、球队、生效轮次与扣分值，从生效轮次起扣分。</p>
      <p v-if="!penalties.length" class="empty">暂无处罚。</p>
      <div v-for="penalty in penalties" :key="penalty.uid" class="penalty-row">
        <input
          v-model="penalty.id"
          aria-label="处罚编号"
          maxlength="40"
          placeholder="编号"
          @input="markDirty"
        />
        <select v-model="penalty.teamUid" aria-label="处罚球队" @change="markDirty">
          <option v-for="team in teams" :key="team.uid" :value="team.uid">{{ team.id }}</option>
        </select>
        <input
          type="number"
          min="1"
          step="1"
          v-model.number="penalty.round"
          aria-label="处罚轮次"
          title="生效轮次"
          @input="markDirty"
        />
        <input
          type="number"
          min="1"
          step="1"
          v-model.number="penalty.points"
          aria-label="处罚扣分"
          title="扣分值"
          @input="markDirty"
        />
        <button type="button" class="secondary" @click="removePenalty(penalty.uid)">删除</button>
      </div>
    </section>

    <section class="card" data-testid="appeals-card">
      <div class="card-title">
        <h2>申诉</h2>
        <button type="button" :disabled="!penalties.length" @click="addAppeal">添加申诉</button>
      </div>
      <p class="hint">
        一次申诉只引用一条既有处罚；生效轮次不得早于处罚轮次，从该轮起撤销该处罚的扣分。
      </p>
      <p v-if="!appeals.length" class="empty">暂无申诉。</p>
      <div v-for="appeal in appeals" :key="appeal.uid" class="appeal-row">
        <select v-model="appeal.penaltyUid" aria-label="申诉处罚" @change="markDirty">
          <option v-for="penalty in penalties" :key="penalty.uid" :value="penalty.uid">
            {{ penalty.id }}
          </option>
        </select>
        <input
          type="number"
          min="1"
          step="1"
          v-model.number="appeal.round"
          aria-label="申诉轮次"
          title="生效轮次"
          @input="markDirty"
        />
        <button type="button" class="secondary" @click="removeAppeal(appeal.uid)">删除</button>
      </div>
    </section>

    <section class="card" data-testid="round-card">
      <div class="card-title">
        <h2>截至轮次排名</h2>
        <p>只统计所选轮次及之前的比赛、处罚与申诉；切换轮次或编辑事件后旧解释立即失效。</p>
      </div>
      <div class="round-controls">
        <label>
          截至轮次
          <input
            type="number"
            min="1"
            step="1"
            v-model.number="selectedRound"
            aria-label="截至轮次"
            data-testid="round-input"
            @input="markDirty"
          />
        </label>
        <button type="button" class="primary" :disabled="roundLoading" @click="calculateAtRound">
          {{ roundLoading ? '计算中…' : '计算截至轮次名次' }}
        </button>
      </div>
      <p v-if="roundError" class="error" data-testid="round-error">{{ roundError }}</p>
    </section>

    <section v-if="roundResult" class="card" data-testid="round-standings-card">
      <div class="card-title">
        <h2>截至第 {{ roundResult.round }} 轮名次</h2>
        <span class="version" data-testid="round-result-version">
          当前请求版本：{{ roundResult.request_id }}
        </span>
      </div>
      <table data-testid="round-standings-table">
        <thead>
          <tr>
            <th>名次</th>
            <th>球队</th>
            <th>比赛积分</th>
            <th>有效扣分</th>
            <th>调整后积分</th>
            <th>场次</th>
            <th>进球</th>
            <th>失球</th>
            <th>净胜球</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in roundResult.standings" :key="row.team">
            <td>{{ row.rank }}</td>
            <td>{{ row.team }}</td>
            <td>{{ row.match_points }}</td>
            <td>{{ row.deduction }}</td>
            <td>{{ row.points }}</td>
            <td>{{ row.played }}</td>
            <td>{{ row.goals_for }}</td>
            <td>{{ row.goals_against }}</td>
            <td>{{ row.goal_difference }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section
      v-if="roundResult && roundResult.tiebreakers.length"
      class="card"
      data-testid="round-trace-card"
    >
      <h2>截至轮次的逐级排名依据</h2>
      <ol class="trace-list">
        <li v-for="(event, index) in roundResult.tiebreakers" :key="index" class="trace-event">
          <p class="trace-basis">
            <strong>{{ basisLabel[event.basis] }}</strong>
            <span>深度 {{ event.depth }} · 球队：{{ event.teams.join(', ') }}</span>
          </p>

          <table v-if="event.basis === 'total_points'" class="mini-table">
            <thead>
              <tr><th>球队</th><th>比赛积分</th><th>有效扣分</th><th>调整后积分</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in pointRows(event)" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.match_points }}</td>
                <td>{{ row.deduction }}</td>
                <td>{{ row.points }}</td>
              </tr>
            </tbody>
          </table>

          <table v-else-if="event.basis === 'head_to_head_points'" class="mini-table">
            <thead>
              <tr><th>球队</th><th>组内积分</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in pointRows(event)" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.points }}</td>
              </tr>
            </tbody>
          </table>

          <table v-else class="mini-table">
            <thead>
              <tr><th>球队</th><th>净胜球</th><th>进球</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in tieRows(event)" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.goal_difference }}</td>
                <td>{{ row.goals_for }}</td>
              </tr>
            </tbody>
          </table>

          <div class="partitions">
            <span v-for="(part, partIndex) in event.partitions" :key="partIndex" class="partition">
              {{ part.join(' = ') }}
            </span>
          </div>
        </li>
      </ol>
    </section>
  </main>
</template>
