import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Tooltip from 'primevue/tooltip'
import Lara from '@primeuix/themes/lara'
import { definePreset } from '@primeuix/themes'

const BotPreset = definePreset(Lara, {
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
  components: {
    select: {
      overlay: {
        background: '#23263d',
        borderColor: '{primary.50}',
      },
      option: {
        color: '{primary.50}',
        focusColor: '{primary.50}',
        focusBackground: '#2b2e4a',
        selectedColor: '{primary.50}',
        selectedBackground: '#363a58',
        selectedFocusColor: '{primary.50}',
        selectedFocusBackground: '#3e4265',
      },
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
app.directive('tooltip', Tooltip)
app.use(i18n)

app.mount('#app')
