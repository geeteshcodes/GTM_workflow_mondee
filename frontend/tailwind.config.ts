import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans:    ["var(--font-dm-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-syne)",    "system-ui", "sans-serif"],
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card:       { DEFAULT: "hsl(var(--card))",    foreground: "hsl(var(--card-foreground))" },
        primary:    { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary:  { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted:      { DEFAULT: "hsl(var(--muted))",   foreground: "hsl(var(--muted-foreground))" },
        accent:     { DEFAULT: "hsl(var(--accent))",  foreground: "hsl(var(--accent-foreground))" },
        destructive:{ DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        success:    { DEFAULT: "hsl(var(--success))", foreground: "hsl(var(--success-foreground))" },
        warning:    { DEFAULT: "hsl(var(--warning))", foreground: "hsl(var(--warning-foreground))" },
        border:     "hsl(var(--border))",
        input:      "hsl(var(--input))",
        ring:       "hsl(var(--ring))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "fade-in":        { from: { opacity: "0" },                     to: { opacity: "1" } },
        "slide-in-bottom":{ from: { transform: "translateY(12px)", opacity: "0" }, to: { transform: "translateY(0)", opacity: "1" } },
        "pulse-border":   { "0%,100%": { "border-color": "hsl(var(--primary)/0.3)" }, "50%": { "border-color": "hsl(var(--primary))" } },
      },
      animation: {
        "fade-in":        "fade-in 0.3s ease-out",
        "slide-in":       "slide-in-bottom 0.4s ease-out",
        "pulse-border":   "pulse-border 2s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
