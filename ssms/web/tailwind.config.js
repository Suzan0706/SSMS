/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Indigo (design/20 §20.6): 500 is the primary #4F46E5 and carries white text at 6.3:1; 900 is the sidebar #1E1B4B.
        brand: {
          50: "#eef2ff", 100: "#e0e7ff", 200: "#c7d2fe", 300: "#a5b4fc", 400: "#818cf8",
          500: "#4f46e5", 600: "#4338ca", 700: "#3730a3", 800: "#312e81", 900: "#1e1b4b", 950: "#13112f",
        },
        // Amber: used sparingly, for the one thing to notice. 700 on 100 reads at 4.9:1.
        accent: { 100: "#fef3c7", 300: "#fcd34d", 500: "#f59e0b", 700: "#b45309" },
      },
      fontFamily: {
        sans: ['"Figtree Variable"', "system-ui", "-apple-system", '"Segoe UI"', "sans-serif"],
        display: ['"Figtree Variable"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px -8px rgb(15 23 42 / 0.10)",
        lift: "0 12px 32px -12px rgb(30 27 75 / 0.30)",
      },
    },
  },
  plugins: [],
};
