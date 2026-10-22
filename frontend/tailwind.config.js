/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#06080d",
          900: "#0a0e15",
          850: "#0e131c",
          800: "#121924",
          700: "#1a2331",
          600: "#243044",
          500: "#34445e",
        },
        bull: "#16c784",
        bear: "#ea3943",
        warn: "#f5a524",
        accent: "#3b82f6",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      keyframes: {
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(22,199,132,0.55)" },
          "100%": { boxShadow: "0 0 0 10px rgba(22,199,132,0)" },
        },
      },
      animation: { pulseRing: "pulseRing 1.6s ease-out infinite" },
    },
  },
  plugins: [],
};
