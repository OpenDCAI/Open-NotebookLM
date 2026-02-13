/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#f2f2f7',
        primary: '#007AFF',
        'ios-gray': {
          50: '#f2f2f7',
          100: '#e5e5ea',
          200: '#d1d1d6',
          300: '#c7c7cc',
          400: '#aeaeb2',
          500: '#8e8e93',
          600: '#636366',
          700: '#48484a',
          800: '#3a3a3c',
          900: '#1c1c1e',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      borderRadius: {
        'ios': '12px',
        'ios-lg': '16px',
        'ios-xl': '20px',
        'ios-2xl': '24px',
      },
      boxShadow: {
        'ios-sm': '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.06)',
        'ios': '0 2px 8px rgba(0,0,0,0.08), 0 1px 4px rgba(0,0,0,0.06)',
        'ios-lg': '0 4px 16px rgba(0,0,0,0.1), 0 2px 8px rgba(0,0,0,0.06)',
        'ios-xl': '0 8px 32px rgba(0,0,0,0.12), 0 4px 16px rgba(0,0,0,0.08)',
      },
      keyframes: {
        'ios-sheet-up': {
          '0%': { transform: 'translateY(100%)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        'ios-fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'ios-shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        'ios-sheet-up': 'ios-sheet-up 0.4s cubic-bezier(0.32, 0.72, 0, 1)',
        'ios-fade-in': 'ios-fade-in 0.25s ease-out',
        'ios-shimmer': 'ios-shimmer 1.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
