import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The server (server/, Python) serves the dashboard at /admin/, so build straight into its static folder
// (no copy step).
export default defineConfig({
  plugins: [react()],
  base: '/admin/',
  build: {
    outDir: '../server/islewarden_server/static/admin',
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` hot-reloads the UI but sends API calls to the locally running server.
    proxy: {
      '/api': 'http://localhost:5088',
    },
  },
})
