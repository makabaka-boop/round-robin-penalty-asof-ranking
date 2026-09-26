<script setup>
import { reactive, ref } from 'vue'

const props = defineProps({
  teams: { type: Array, required: true },
  matches: { type: Array, required: true },
  teamById: { type: Map, required: true }
})
const emit = defineEmits(['edit'])

const store = reactive({ loading: false })
const errorMessage = ref('')
const result = ref(null)
// requestSeq identifies a particular request and is echoed by the API;
// editSeq is bumped by every form edit so a response that was in flight
// before the edit can never populate the page again.
const requestSeq = ref(0)
const editSeq = ref(0)

function markDirty() {
  editSeq.value += 1
  result.value = null
  errorMessage.value = ''
  store.loading = false
}

defineExpose({ markDirty })

function payloadError() {
  const ids = props.teams.map((team) => team.id)
  if (ids.some((id) => !/^[\x21-\x7E]{1,40}$/.test(id))) {
    return '球队 id 必须是 1 至 40 个非空白 ASCII 字符。'
  }
  if (new Set(ids).size !== ids.length) return '球队 id 必须唯一。'
  const badScore = props.matches.some(
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
  store.loading = true
  errorMessage.value = ''

  try {
    const response = await fetch('/api/rankings', {
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
      store.loading = false
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
  total_points: '总积分并列组',
  head_to_head_points: '按当前并列组内比赛积分拆分；剩余子组会重新计算',
  global_tiebreakers: '无法继续拆分，按全局净胜球 → 全局进球 → 球队 id ASCII 字节序'
}
</script>

<template>
  <div>
    <section class="card" data-testid="matches-card">
      <div class="card-title">
        <h2>已赛比分</h2>
        <p>每对球队至多一场；未勾选表示尚未比赛。</p>
      </div>
      <div class="matches">
        <div v-for="match in matches" :key="match.a + '-' + match.b" class="match-row">
          <label>
            <input
              type="checkbox"
              :checked="match.played"
              @change="(event) => { match.played = event.target.checked; emit('edit'); markDirty() }"
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
            @input="(event) => { match.homeScore = event.target.value === '' ? null : Number(event.target.value); emit('edit'); markDirty() }"
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
            @input="(event) => { match.awayScore = event.target.value === '' ? null : Number(event.target.value); emit('edit'); markDirty() }"
          />
          <span>{{ teamLabel(match.b) }}</span>
        </div>
      </div>
    </section>

    <div class="actions">
      <button type="button" class="primary" :disabled="store.loading" @click="calculate">
        {{ store.loading ? '计算中…' : '计算名次' }}
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
  </div>
</template>
