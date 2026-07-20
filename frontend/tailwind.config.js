/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f7f9fc",
        ink: "#111827",
        muted: "#667085",
        line: "#e5e9f0",
        brand: "#1769ff",
        success: "#12b76a",
        warning: "#f79009",
        danger: "#f04438"
      },
      borderRadius: { panel: "8px" },
      boxShadow: { panel: "0 1px 2px rgba(16,24,40,.04),0 1px 6px rgba(16,24,40,.025)" },
      fontFamily: { sans: ["Inter", "Noto Sans SC", "Microsoft YaHei", "sans-serif"] }
    }
  },
  plugins: []
};
