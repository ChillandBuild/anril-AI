import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#ffffff",
        surface: "#ffffff",
        "surface-mid": "#f1f5f9",
        "surface-low": "#ffffff",
        "surface-subtle": "#ffffff",

        // Brand primary = Anril teal #038285 (800 = DEFAULT). Every button,
        // link, active tab and highlight reads this one scale.
        // 950 is deliberately NAVY #0A1528, not a deeper teal: the "darkest
        // brand" uses (dark panels, gradients) are navy sections.
        // DEFAULT/dark/light/muted are aliases so existing bg-primary /
        // bg-primary-dark / etc. usages keep working.
        primary: {
          DEFAULT: "#038285",
          50: "#effbfb",
          100: "#d5f4f4",
          200: "#ade9ea",
          300: "#78d6d8",
          400: "#3fbcbf",
          500: "#1aa3a6",
          600: "#0b9396",
          700: "#068a8d",
          800: "#038285",
          900: "#04585b",
          950: "#0A1528",
          dark: "#04585b",
          light: "#effbfb",
          muted: "#d5f4f4",
        },

        // Navy: headings, body text, dark sections. navy-accent is the light
        // teal for text/icons ON navy (#038285 on navy is only ~3.9:1).
        navy: {
          DEFAULT: "#0A1528",
          800: "#13284A",
          700: "#1E3A5F",
        },
        "navy-accent": "#3fbcbf",

        // ink / ink-muted / on-surface-muted read CSS variables (defaults in globals.css = the same
        // hex values as before) so "Darker text" in Settings can swap the muted ones.
        ink: "rgb(var(--ink-rgb) / <alpha-value>)",
        "ink-secondary": "#475569",
        "ink-muted": "rgb(var(--ink-muted-rgb) / <alpha-value>)",

        border: "#e2e8f0",
        "border-subtle": "#f1f5f9",

        success: "#15803d",
        warning: "#d97706",
        danger: "#e11d48",

        secondary: "#0A1528",
        "secondary-light": "#475569",
        "secondary-bg": "#f1f5f9",
        "secondary-text": "#0A1528",
        tertiary: "#13284A",
        "on-surface": "#0A1528",
        "on-surface-muted": "rgb(var(--on-surface-muted-rgb) / <alpha-value>)",

        "segment-a-bg": "#ecfdf5",
        "segment-a-text": "#15803d",
        "segment-a-border": "#bbf7d0",
        "segment-b-bg": "#fffbeb",
        "segment-b-text": "#d97706",
        "segment-b-border": "#fde68a",
        "segment-c-bg": "#f8fafc",
        "segment-c-text": "#64748b",
        "segment-c-border": "#e2e8f0",
        "segment-d-bg": "#fff1f2",
        "segment-d-text": "#e11d48",
        "segment-d-border": "#fecdd3",
      },
      fontFamily: {
        display: ["var(--font-manrope)", "sans-serif"],
        body: ["var(--font-manrope)", "sans-serif"],
        label: ["var(--font-manrope)", "sans-serif"],
        // Opt-in display face (Archivo). See app/layout.tsx for why this is a
        // separate role rather than a repoint of `display`.
        heading: ["var(--font-heading)", "var(--font-manrope)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      boxShadow: {
        card: "0 2px 16px -2px rgba(10,21,40,.07), 0 1px 4px -1px rgba(10,21,40,.04)",
        "card-hover": "0 8px 28px -4px rgba(10,21,40,.12), 0 3px 8px -2px rgba(10,21,40,.05)",
        sidebar: "0 4px 30px rgba(10,21,40,.03)",
        sm: "0 1px 2px rgba(10,21,40,.04)",
      },
      borderRadius: {
        card: "1.25rem",
        xl: "0.875rem",
        "2xl": "1.125rem",
        "3xl": "1.25rem",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #0A1528 0%, #13284A 100%)",
        "warm-base": "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
      },
      zIndex: {
        // Shared stacking convention for the dashboard shell. The mobile
        // bottom nav (`z-bottom-nav`) must stay BELOW every modal/dialog
        // overlay (`z-dialog`) so opening a dialog on a phone never leaves
        // the bar drawn on top of it. Keep new fixed-position dashboard
        // overlays on one of these two tokens instead of ad-hoc z-50/z-60.
        "bottom-nav": "60",
        dialog: "100",
      },
    },
  },
  plugins: [],
};
export default config;
