import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#f0f3f9',
          100: '#d9e0ef',
          200: '#b3c1df',
          300: '#8da2cf',
          400: '#6783bf',
          500: '#4164af',
          600: '#1a3a6b',
          700: '#142d54',
          800: '#0f203d',
          900: '#0a1428',
          950: '#050a14',
        },
        slate: {
          850: '#172033',
        },
        accent: {
          50: '#fff8ed',
          100: '#ffeed4',
          200: '#ffdba9',
          300: '#ffc57e',
          400: '#ffaf53',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'hero-pattern': 'linear-gradient(135deg, #0a1428 0%, #142d54 40%, #1a3a6b 100%)',
      },
    },
  },
  plugins: [],
};

export default config;
