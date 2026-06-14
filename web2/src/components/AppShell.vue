<script setup>
import BottomNav from './BottomNav.vue'

defineProps({
  title: { type: String, default: '' },
})
</script>

<template>
  <div class="app">
    <header class="app-header">
      <h1>{{ title }}</h1>
      <slot name="actions" />
    </header>
    <main class="app-main">
      <slot />
    </main>
    <BottomNav />
  </div>
</template>
