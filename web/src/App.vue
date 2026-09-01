<template>
  <router-view />
  <div v-if="toast" class="toast">{{ toast }}</div>
</template>

<script setup>
import { ref, provide } from 'vue'
import { formatError } from './api'

const toast = ref('')
function showError(err) {
  toast.value = formatError(err)
  setTimeout(() => {
    if (toast.value === formatError(err)) toast.value = ''
  }, 4200)
}
provide('showError', showError)
</script>
