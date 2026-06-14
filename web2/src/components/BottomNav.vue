<script setup>
const tabs = [
  { to: '/hoy', label: 'Hoy', ic: '🏠' },
  { to: '/finanzas', label: 'Finanzas', ic: '💸' },
  { to: '/plan', label: 'Plan', ic: '🗺️' },
  { to: '/perfil', label: 'Perfil', ic: '👤' },
]
</script>

<template>
  <nav class="bottom-nav">
    <router-link
      v-for="t in tabs"
      :key="t.to"
      :to="t.to"
      :class="{ active: $route.path === t.to }"
    >
      <span class="ic">{{ t.ic }}</span>
      {{ t.label }}
    </router-link>
  </nav>
</template>
