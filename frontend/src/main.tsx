import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Apply saved theme before React mounts to avoid a flash of wrong colour scheme
const saved = localStorage.getItem("theme") ?? "system"
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
if (saved === "dark" || (saved === "system" && prefersDark)) {
  document.documentElement.classList.add("dark")
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
