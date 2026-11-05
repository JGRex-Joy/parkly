/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        base: '#0d1117',
        panel: '#111826',
        neon: { emerald: '#10b981', coral: '#ef4444', cyan: '#06b6d4' },
      },
      fontFamily: {
        display: ['Orbitron', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 18px rgba(6,182,212,.45)',
        'glow-emerald': '0 0 18px rgba(16,185,129,.45)',
        'glow-coral': '0 0 18px rgba(239,68,68,.45)',
      },
    },
  },
  plugins: [],
}
