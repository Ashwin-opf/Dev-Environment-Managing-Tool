# Design Document: SHCE GSAP Animation System

## Overview

The GSAP animation system adds a premium cinematic layer to PC Doctor's existing vanilla JS/HTML/CSS frontend. It is implemented as a single self-contained file `frontend/animations.js` loaded after `main.js`. It uses GSAP 3.12.5 + ScrollTrigger from CDN, a MutationObserver to detect view and tab changes, and gracefully degrades if GSAP is unavailable.

## Architecture

```
index.html
  └── main.js (existing)
  └── gsap.min.js (CDN)
  └── ScrollTrigger.min.js (CDN)
  └── animations.js (new)
       ├── window.PCDoctorAnimations = { init(), destroy() }
       ├── startBgParticles()       — ambient canvas particles
       ├── initNavIndicator()       — sliding nav highlight
       ├── initSHCEScrollReveal()  — scroll-driven card reveal
       ├── initCardHover()         — card hover lift effect
       ├── animateTileValues()     — count-up for stat tiles
       ├── onViewActivated(id)     — dispatched by MutationObserver
       ├── onSHCETabActivated(id) — dispatched by MutationObserver
       └── injectSettingsToggle() — pill switch in sidebar footer
```

## Components

### animations.js
- **IIFE** wrapping entire codebase — zero global pollution except `window.PCDoctorAnimations`
- Checks `localStorage.getItem('pc_doctor_animations_enabled') !== 'false'` at load time
- Top-level try/catch — any error silently degrades without breaking main.js
- `gsap.config({ force3D: true })` for hardware-accelerated transforms
- `ScrollTrigger.config({ limitCallbacks: true })` to reduce callback spam

### Background Particles (Req 11)
- Canvas element injected as first child of `<body>`
- `position: fixed; pointer-events: none; z-index: 0; opacity: 0.3`
- 28 particles with colors from app palette (`#0a84ff`, `#bf5af2`, `#5ac8fa`)
- `requestAnimationFrame` loop with drift velocity ≤ 0.3px/frame
- Cancelled and removed on `destroy()` or toggle off

### Navigation Slide Indicator (Req 10)
- Single `<div class="nav-slide-indicator">` injected into `.sidebar-nav`
- `MutationObserver` on `.sidebar-nav` watches for `.nav-item.active` class changes
- `gsap.to()` with `elastic.out(1, 0.75)` easing animates top/height
- Icon glow via `filter: drop-shadow(0 0 6px rgba(10,132,255,0.7))`

### SHCE Scroll Reveal (Req 3, 4)
- Uses `ScrollTrigger.batch()` for performance (handles 60+ cards)
- Stat tiles: `{ opacity: 0, y: 40, scale: 0.95 }` → visible, stagger 0.06s
- Panel cards: `{ opacity: 0, y: 50, scale: 0.96 }` → visible, stagger 0.05s
- Inner stagger for headings → text → buttons → data
- `will-change` set before animation, cleared after via `clearProps`

### Card Hover (Req 5)
- Delegated event listeners on `.main-wrapper` — handles dynamic cards
- `translateY(-6px) scale(1.02)` with custom box-shadow on enter
- Reversed on leave — no competing CSS transitions

### Tab Animations (Req 7, 8, 9)
- Queue: slide-in from left (-24px), pulse red/green borders on risk nodes
- Errors: fade up, character-by-character command reveal
- Knowledge: stagger up with back.out easing
- History: slide-in from left
- Environment: scale-in with back.out

### Settings Toggle (Req 2)
- Pill toggle injected into `.sidebar-footer`
- Changes `localStorage.getItem('pc_doctor_animations_enabled')`
- Toggle off: kills all tweens, removes canvas, restores elements
- Toggle on: re-initializes everything for current view

## CSS Additions (style.css)

```css
/* Animation toggle switch */
.anim-toggle-switch input { opacity: 0; width: 0; height: 0; }
.anim-toggle-slider { position: absolute; inset: 0; border-radius: 11px; background: rgba(255,255,255,0.15); transition: background 0.25s; }
.anim-toggle-slider:before { content: ''; position: absolute; width: 16px; height: 16px; border-radius: 50%; background: white; transition: left 0.25s; }
input:checked + .anim-toggle-slider { background: #0a84ff; }
input:checked + .anim-toggle-slider:before { left: 21px; }
```

## index.html Changes

1. GSAP CDN script tags before `</body>`
2. `animations.js` script tag after `main.js`
3. Animations toggle in settings panel

## Performance Strategy

- Transform + opacity only in all tweens
- `force3D: true` for all elements
- `ScrollTrigger.batch()` instead of individual instances
- `will-change` lifecycle managed (set before, cleared after)
- Particle canvas uses Canvas 2D API — no layout reflow
- `limitCallbacks: true` reduces ScrollTrigger overhead
- Dropped frame detection via GSAP ticker

## Correctness Properties

1. If GSAP fails to load, app works normally — no errors thrown
2. Toggle off restores all elements to fully visible
3. Toggle persists across page reloads via localStorage
4. All animations use transform/opacity only
5. MutationObserver connects only once per init, disconnects on destroy
