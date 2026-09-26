<script setup>
import { reactive, ref } from 'vue'

const props = defineProps({
  teams: { type: Array, required: true },
  matches: { type: Array, required: true },
  teamById: { type: Map, required: true }
})
const emit = defineEmits(['edit'])

let penaltyUid = 0
function nextPenaltyUid() {
  penaltyUid += 1
  return `penalty-${penaltyUid}`
}

function makePenalty() {
  return reactive({
    uid: nextPenaltyUid(),
    id: `P${penaltyUid}`,
    teamUid: props.teams[0]?.uid ?? '',
    effectiveRound: 1,
    deduction: 1,
    appealRound: null
  })
}

// The snapshot flow owns its own discipline events and round selector.
const penalties = ref([
  reactive({
    uid: nextPenaltyUid(),
    id: 'P1',
    teamUid: '',
    effectiveRound: 1,
    deduction: 1,
    appealRound: null
  })
])
if (props.teams[0]) penalties.value[0].teamUid = props.teams[0].uid

const asOfRound = ref(1)
const loading = ref(false)
const errorMessage = ref('')
const result = ref(null)
// requestSeq is echoed by the API; editSeq bumps on every edit and roundSeq
// whenever the selected round changes, so a late response from another round
// or an older edit can never overwrite the current view.
const requestSeq = ref(0)
const editSeq = ref(0)
const roundSeq = ref(0)

function invalidate() {
  editSeq.value += 1
  result.value = null
  errorMessage.value = ''
  loading.value = false
}

function changeRound(event) {
  const value = Number(event.target.value)
  if (Number.isInteger(value) && value >= 1) {
    asOfRound.value = value
    roundSeq.value += 1
    result.value = null
    errorMessage.value = ''
    loading.value = false
  }
}

function addPenalty() {
  penalties.value.push(makePenalty())
  invalidate()
}

function removePenalty(uid) {
  penalties.value = penalties.value.filter((penalty) => penalty.uid !== uid)
  invalidate()
}

function edited() {
  emit('edit')
  invalidate()
}

function teamOptions() {
  return props.teams
}

function penaltyTeamId(penalty) {
  return props.teamById.get(penalty.teamUid)?.id ?? ''
}

function payloadError() {
  const ids = new Set(props.teams.map((team) => team.id))
  if (ids.size !== props.teams.length) return '球队 id 必须唯一。'
  if (props.teams.some((team) => !/^[\x21-\x7E]{1,40}$/.test(team.id))) {
    return '球队 id 必须是 1 至 40 个非空白 ASCII 字符。'
  }

  const badScore = props.matches.some(
    (match) =>
      match.played &&
      (!Number.isInteger(match.round) ||
        match.round < 1 ||
        !Number.isInteger(match.homeScore) ||
        !Number.isInteger(match.awayScore) ||
        match.homeScore < 0 ||
        match.homeScore > 20 ||
        match.awayScore < 0 ||
        match.awayScore > 20)
  )
  if (badScore) return '已赛比赛必须填写正整数轮次与 0 至 20 的整数比分。'

  const seenPenaltyIds = new Set()
  for (const penalty of penalties.value) {
    if (!/^[\x21-\x7E]{1,40}$/.test(penalty.id)) return '处罚编号必须是 1 至 40 个非空白 ASCII 字符。'
    if (seenPenaltyIds.has(penalty.id)) return `处罚编号 ${penalty.id} 重复。`
    seenPenaltyIds.add(penalty.id)
    if (!ids.has(penaltyTeamId(penalty))) return `处罚 ${penalty.id} 引用了不存在的球队。`
    if (!Number.isInteger(penalty.effectiveRound) || penalty.effectiveRound < 1) {
      return `处罚 ${penalty.id} 的生效轮次必须是正整数。`
    }
    if (!Number.isInteger(penalty.deduction) || penalty.deduction < 1) {
      return `处罚 ${penalty.id} 的扣分值必须是正整数。`
    }
    if (
      penalty.appealRound !== null &&
      penalty.appealRound !== '' &&
      (!Number.isInteger(penalty.appealRound) ||
        penalty.appealRound < 1 ||
        penalty.appealRound < penalty.effectiveRound)
    ) {
      return `处罚 ${penalty.id} 的申诉生效轮次不得早于处罚本身。`
    }
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
  const roundAtRequest = roundSeq.value
  loading.value = true
  errorMessage.value = ''

  const payloadPenalties = penalties.value.map((penalty) => ({
    id: penalty.id,
    team: penaltyTeamId(penalty),
    effective_round: penalty.effectiveRound,
    deduction: penalty.deduction
  }))
  const payloadAppeals = penalties.value
    .filter((penalty) => penalty.appealRound !== null && penalty.appealRound !== '')
    .map((penalty) => ({
      penalty_id: penalty.id,
      effective_round: penalty.appealRound
    }))

  try {
    const response = await fetch('/api/rankings/as-of-round', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId,
        teams: props.teams.map((team) => team.id),
        matches: props.matches
          .filter((match) => match.played)
          .map((match) => ({
            home: props.teamById.get(match.a).id,
            away: props.teamById.get(match.b).id,
            home_score: match.homeScore,
            away_score: match.awayScore,
            round: match.round
          })),
        penalties: payloadPenalties,
        appeals: payloadAppeals,
        as_of_round: asOfRound.value
      })
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '截至轮次排名接口返回错误')
    // A response is only current when request id, edit state and selected
    // round all match; otherwise it is a late response and must be dropped.
    if (
      data.request_id !== requestId ||
      editSeq.value !== editAtRequest ||
      roundSeq.value !== roundAtRequest
    ) {
      return
    }
    result.value = data
  } catch (error) {
    if (
      requestId === requestSeq.value &&
      editSeq.value === editAtRequest &&
      roundSeq.value === roundAtRequest
    ) {
      errorMessage.value = error.message
    }
  } finally {
    if (
      requestId === requestSeq.value &&
      editSeq.value === editAtRequest &&
      roundSeq.value === roundAtRequest
    ) {
      loading.value = false
    }
  }
}

function teamLabel(uid) {
  return props.teamById.get(uid)?.id ?? '?'
}

function pointRows(event) {
  const source = event.head_to_head_points || event.points || {}
  return Object.values(source).sort((a, b) => a.id.localeCompare(b.id))
}

function tieRows(event) {
  return event.values ? Object.values(event.values).sort((a, b) => a.id.localeCompare(b.id)) : []
}

const basisLabel = {
  adjusted_total_points: '调整后总积分并列组（比赛积分 − 有效扣分）',
  head_to_head_points: '组内相互战绩只由已赛比赛计算；剩余子组重新计算',
  global_tiebreakers: '无法继续拆分，按全局净胜球 → 全局进球 → 球队 id ASCII 字节序'
}
</script>

<template>
  <div>
    <section class="card" data-testid="matches-round-card">
      <div class="card-title">
        <h2>比赛与轮次</h2>
        <p>仅“轮次 ≤ 截至轮次”的已赛比赛参与计算；之后的比赛不进入过去的榜单。</p>
      </div>
      <div class="matches">
        <div v-for="match in matches" :key="match.a + '-' + match.b" class="match-row">
          <label>
            <input
              type="checkbox"
              :checked="match.played"
              @change="(event) => { match.played = event.target.checked; edited() }"
            />
            <span>{{ teamLabel(match.a) }}</span>
          </label>
          <input
            class="score"
            type="number"
            min="0"
            max="20"
            step="1"
            :disabled="!match.played"
            :value="match.homeScore"
            aria-label="主队比分"
            @input="(event) => { match.homeScore = event.target.value === '' ? null : Number(event.target.value); edited() }"
          />
          <span>:</span>
          <input
            class="score"
            type="number"
            min="0"
            max="20"
            step="1"
            :disabled="!match.played"
            :value="match.awayScore"
            aria-label="客队比分"
            @input="(event) => { match.awayScore = event.target.value === '' ? null : Number(event.target.value); edited() }"
          />
          <span>{{ teamLabel(match.b) }}</span>
          <label class="round-label">
            第
            <input
              class="round-input"
              type="number"
              min="1"
              step="1"
              :disabled="!match.played"
              :value="match.round"
              aria-label="比赛轮次"
              @input="(event) => { match.round = event.target.value === '' ? '' : Number(event.target.value); edited() }"
            />
            轮
          </label>
        </div>
      </div>
    </section>

    <section class="card" data-testid="penalties-card">
      <div class="card-title">
        <h2>处罚与申诉</h2>
        <button type="button" @click="addPenalty">新增处罚</button>
      </div>
      <table data-testid="penalties-table" class="penalties-table">
        <thead>
          <tr>
            <th>唯一编号</th>
            <th>球队</th>
            <th>处罚生效轮次</th>
            <th>扣分值</th>
            <th>申诉生效轮次（留空表示未申诉）</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="penalty in penalties" :key="penalty.uid">
            <td>
              <input
                class="penalty-id"
                v-model="penalty.id"
                maxlength="40"
                aria-label="处罚编号"
                @input="edited"
              />
            </td>
            <td>
              <select
                class="penalty-team"
                v-model="penalty.teamUid"
                aria-label="处罚球队"
                @change="edited"
              >
                <option v-for="team in teamOptions()" :key="team.uid" :value="team.uid">
                  {{ team.id }}
                </option>
              </select>
            </td>
            <td>
              <input
                class="penalty-round"
                type="number"
                min="1"
                step="1"
                v-model.number="penalty.effectiveRound"
                aria-label="处罚生效轮次"
                @input="edited"
              />
            </td>
            <td>
              <input
                class="penalty-deduction"
                type="number"
                min="1"
                step="1"
                v-model.number="penalty.deduction"
                aria-label="扣分值"
                @input="edited"
              />
            </td>
            <td>
              <input
                class="appeal-round"
                type="number"
                min="1"
                step="1"
                :value="penalty.appealRound"
                placeholder="无"
                aria-label="申诉生效轮次"
                @input="(event) => { penalty.appealRound = event.target.value === '' ? null : Number(event.target.value); edited() }"
              />
            </td>
            <td>
              <button type="button" class="secondary" @click="removePenalty(penalty.uid)">
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card" data-testid="as-of-card">
      <div class="card-title">
        <h2>截至轮次</h2>
        <p>只统计该轮结束时真实生效的处罚；申诉从其生效轮次起撤销扣分。</p>
      </div>
      <label class="as-of-picker">
        查看第
        <input
          data-testid="as-of-round-input"
          class="round-input"
          type="number"
          min="1"
          step="1"
          :value="asOfRound"
          aria-label="截至轮次"
          @input="changeRound"
        />
        轮结束时的名次
      </label>
    </section>

    <div class="actions">
      <button
        type="button"
        class="primary"
        data-testid="as-of-calculate"
        :disabled="loading"
        @click="calculate"
      >
        {{ loading ? '计算中…' : '计算截至该轮名次' }}
      </button>
      <p v-if="errorMessage" class="error" data-testid="as-of-error">{{ errorMessage }}</p>
    </div>

    <section v-if="result" class="card" data-testid="as-of-standings-card">
      <div class="card-title">
        <h2>截至第 {{ result.as_of_round }} 轮名次</h2>
        <span class="version" data-testid="as-of-result-version">
          请求版本：{{ result.request_id }} · 截至轮次：{{ result.as_of_round }}
        </span>
      </div>
      <table data-testid="as-of-standings-table">
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
          <tr v-for="row in result.standings" :key="row.team">
            <td>{{ row.rank }}</td>
            <td>{{ row.team }}</td>
            <td>{{ row.match_points }}</td>
            <td>
              {{ row.deductions }}
              <span v-if="row.active_penalties.length" class="penalty-refs">
                （{{ row.active_penalties.map((p) => p.id + ' −' + p.deduction).join('，') }}）
              </span>
            </td>
            <td><strong>{{ row.adjusted_points }}</strong></td>
            <td>{{ row.played }}</td>
            <td>{{ row.goals_for }}</td>
            <td>{{ row.goals_against }}</td>
            <td>{{ row.goal_difference }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section
      v-if="result && result.tiebreakers.length"
      class="card"
      data-testid="as-of-trace-card"
    >
      <h2>逐级排名依据</h2>
      <ol class="trace-list">
        <li v-for="(event, index) in result.tiebreakers" :key="index" class="trace-event">
          <p class="trace-basis">
            <strong>{{ basisLabel[event.basis] }}</strong>
            <span>深度 {{ event.depth }} · 球队：{{ event.teams.join(', ') }}</span>
          </p>

          <table v-if="event.basis !== 'global_tiebreakers'" class="mini-table">
            <thead>
              <tr>
                <th>球队</th>
                <th>{{ event.depth === 0 ? '调整后积分' : '组内比赛积分' }}</th>
              </tr>
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
  </div>
</template>
