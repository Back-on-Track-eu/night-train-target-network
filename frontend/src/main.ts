import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'
import { definePreset } from '@primeuix/themes'

const BotPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '#eef4fb',
      100: '#d5e6f4',
      200: '#add0e8',
      300: '#7db5d9',
      400: '#4e96c9',
      500: '#2271b3',
      600: '#1c5d96',
      700: '#164b7b',
      800: '#103960',
      900: '#0a2646',
      950: '#061529',
    },
  },
})
import 'primeicons/primeicons.css'
import '@mdi/font/css/materialdesignicons.css'
import { i18n } from './i18n'
import App from './App.vue'
import './style.css'

const app = createApp(App)

app.use(createPinia())
app.use(PrimeVue, {
  theme: {
    preset: BotPreset,
    options: {
      darkModeSelector: '.dark',
      cssLayer: {
        name: 'primevue',
        order: 'tailwind-base, primevue, tailwind-utilities',
      },
    },
  },
})
app.use(i18n)

app.mount('#app')
