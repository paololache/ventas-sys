import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#1f3a5f", light: "#e8eef6" },
        sev: { alta: "#b91c1c", media: "#c2410c", baja: "#6b7280" },
      },
    },
  },
  plugins: [],
};
export default config;
