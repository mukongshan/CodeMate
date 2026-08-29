/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'surface-1': '#fcfcfb',
        'surface-2': '#f9f9f7',
        'surface-3': '#f1f0ec',
        'text-primary': '#0b0b0b',
        'text-secondary': '#52514e',
        'text-muted': '#898781',
        'border': 'rgba(11, 11, 11, 0.10)',
        'border-strong': 'rgba(11, 11, 11, 0.18)',
        'gridline': '#e1e0d9',
        'accent': '#2a78d6',
        'lane-blue': '#2a78d6',
        'lane-orange': '#eb6834',
        'lane-aqua': '#1baf7a',
        'lane-yellow': '#eda100',
        'status-pending': '#eda100',
        'status-success': '#0ca30c',
        'status-warning': '#fab219',
        'status-error': '#d03b3b',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'Segoe UI', 'Noto Sans SC', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        'xs': '12px',
        'sm': '13px',
        'base': '14px',
        'lg': '16px',
      },
      spacing: {
        '1': '4px',
        '2': '8px',
        '3': '12px',
        '4': '16px',
        '6': '24px',
        '8': '32px',
      },
      borderRadius: {
        'sm': '6px',
        'md': '10px',
        'lg': '14px',
      },
      boxShadow: {
        'card': '0 1px 2px rgba(11,11,11,.06)',
        'pop': '0 8px 24px rgba(11,11,11,.12)',
      },
      animation: {
        'spin': 'spin 1.2s linear infinite',
      },
    },
  },
  plugins: [],
}
