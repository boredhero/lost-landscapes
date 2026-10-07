import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: { 'no-empty': ['error', { allowEmptyCatch: true }] },
  },
  {
    // Preserve the inherited API/event types; new explorer code keeps strict linting.
    files: ['src/api/client.ts', 'src/components/Map/*.tsx', 'src/components/Sidebar/*.tsx',
      'src/hooks/useDetections.ts', 'src/hooks/useJobProgress.ts',
      'src/pages/LandingPage.tsx', 'src/pages/PlaygroundPage.tsx'],
    rules: { '@typescript-eslint/no-explicit-any': 'off' },
  },
])
