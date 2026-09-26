<script setup>
import { computed, reactive, ref } from 'vue'
import CurrentBoard from './CurrentBoard.vue'
import AsOfBoard from './AsOfBoard.vue'

let uidCounter = 0
const nextUid = () => `team-${++uidCounter}`

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
  const matches = []
  for (let i = 0; i < teams.length; i += 1) {
    for (let j = i + 1; j < teams.length; j += 1) {
      const a = teams[i].uid
      const b = teams[j].uid
      const key = teams[i].id + teams[j].id
      const [hs, as] = initialScores[key] ?? [null, null]
      matches.push(makeMatch(a, b, key in initialScores, hs, as))
    }
  }
  return { teams, matches }
}

const seed = reactive(initialState())
const teams = seed.teams
const matches = seed.matches

const teamById = computed(() => {
  const map = new Map()
  teams.forEach((team) => map.set(team.uid, team))
  return map
})

// The two flows are independent: switching tabs never sends a request and
// each board guards its own stale responses.
const activeTab = ref('current')
const currentBoard = ref(null)
const asOfBoard = ref(null)

function markBothDirty() {
  currentBoard.value?.markDirty()
}

function addTeam() {
  if (teams.length >= 12) return
  const team = reactive({ uid: nextUid(), id: String.fromCharCode(65 + teams.length) })
  teams.forEach((existing) => {
    matches.push(makeMatch(existing.uid, team.uid))
  })
  teams.push(team)
  markBothDirty()
}

function removeTeam(uid) {
  if (teams.length <= 4) return
  const index = teams.findIndex((team) => team.uid === uid)
  teams.splice(index, 1)
  for (let i = matches.length - 1; i >= 0; i -= 1) {
    if (matches[i].a === uid || matches[i].b === uid) matches.splice(i, 1)
  }
  markBothDirty()
}

const tabs = [
  { id: 'current', label: '当前排名' },
  { id: 'as-of', label: '截至轮次排名' }
]
</script>

<template>
  <main class="page">
    <header>
      <p class="eyebrow">无持久化排名服务</p>
      <h1>联赛积分与递归相互战绩</h1>
      <p class="intro">
        先按总积分分组；并列时只统计当前组内比赛，拆出的子组重新计算相互战绩。
        若仍无法拆分，再统一使用全局净胜球、全局进球和 ASCII 字节序。
        “截至轮次排名”只看所选轮次结束时已赛的比赛与当时仍在生效的处罚。
      </p>
    </header>

    <nav class="tabs" data-testid="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        class="tab"
        :class="{ active: activeTab === tab.id }"
        :data-testid="`tab-${tab.id}`"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </nav>

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
            @input="markBothDirty"
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

    <CurrentBoard
      v-if="activeTab === 'current'"
      ref="currentBoard"
      :teams="teams"
      :matches="matches"
      :team-by-id="teamById"
    />
    <AsOfBoard
      v-if="activeTab === 'as-of'"
      ref="asOfBoard"
      :teams="teams"
      :matches="matches"
      :team-by-id="teamById"
    />
  </main>
</template>
