<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])
function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="sheet-overlay" @click.self="close">
      <div class="sheet">
        <div class="sheet-grip" />
        <div class="sheet-head">
          <h3>{{ title }}</h3>
          <button class="x" type="button" @click="close">✕</button>
        </div>
        <slot />
      </div>
    </div>
  </Teleport>
</template>
