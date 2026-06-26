import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon-32.png", "apple-touch-icon.png"],
      manifest: {
        name: "MedLaudo-AI — Assistente de Laudo",
        short_name: "MedLaudo-AI",
        description:
          "Assistente de IA para laudo de raio-X de tórax. Revisão e assinatura sempre por médico.",
        lang: "pt-BR",
        theme_color: "#0f1620",
        background_color: "#0f1620",
        display: "standalone",
        orientation: "any",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,png,jpg,svg,ico,webmanifest}"],
        navigateFallback: "/index.html",
      },
    }),
  ],
  server: { port: 5173 },
});
