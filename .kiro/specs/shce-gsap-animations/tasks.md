# Implementation Plan: SHCE GSAP Animation System

## Overview

Implements the GSAP premium animation layer for PC Doctor's SHCE Control Center and global UI. All code lives in `frontend/animations.js`. The GSAP CDN scripts and the animations toggle are added to `index.html`. Animation CSS is added to `style.css`.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1", "2"] },
    { "wave": 2, "tasks": ["3", "4", "5"] },
    { "wave": 3, "tasks": ["6", "7", "8"] },
    { "wave": 4, "tasks": ["9", "10"] },
    { "wave": 5, "tasks": ["11"] }
  ]
}
```

## Tasks

- [x] 1. Add GSAP CDN scripts and animations.js to index.html
  - Add `<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js">` before `</body>`
  - Add `<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js">` after GSAP
  - Add `<script src="animations.js?v=1.0">` after main.js
  - Add animations toggle (pill switch) to settings panel in index.html
  - _Requirements: 1.1, 1.2, 1.3, 2.1_

- [x] 2. Create animations.js with core architecture
  - IIFE wrapping with try/catch graceful degradation
  - Check localStorage key at startup
  - gsap.config({ force3D: true }) and ScrollTrigger registration
  - Expose window.PCDoctorAnimations = { init(), destroy() }
  - DOMContentLoaded auto-init
  - _Requirements: 1.4, 1.5, 1.6, 13.1, 13.2, 13.3, 13.4, 13.6_

- [x] 3. Implement background ambient particles
  - Inject canvas as first body child (fixed, pointer-events: none, z-index: 0)
  - 28 particles with accent palette colors, velocity ≤ 0.3px/frame
  - requestAnimationFrame loop with drift and opacity oscillation
  - stopBgParticles() removes canvas and cancels RAF
  - _Requirements: 11.1, 11.2, 11.5_

- [x] 4. Implement navigation slide indicator
  - Inject .nav-slide-indicator into .sidebar-nav
  - MutationObserver watches .nav-item.active class changes
  - gsap.to() with elastic.out(1, 0.75) easing on top/height
  - Icon glow filter animation on active/inactive transitions
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 5. Implement card hover microinteraction
  - Delegated mouseenter/mouseleave on .main-wrapper
  - translateY(-6px) scale(1.02) box-shadow on enter
  - Reversed on leave with power2.inOut
  - Disabled when animations off
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. Implement SHCE scroll reveal (Japanese Story Scroll)
  - ScrollTrigger.batch() for stat tiles and panel cards
  - Enter: opacity 0→1, y 50→0, scale 0.96→1, duration 0.8s, power4.out
  - Exit: opacity 0.7, scale 0.97, duration 0.35s
  - will-change lifecycle: set before, clearProps after
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 12.1, 12.2, 12.3_

- [x] 7. Implement staggered card content animation
  - Headings → text → buttons → data → controls, 0.08s stagger
  - opacity 0→1, y 12→0, duration 0.35s, power2.out
  - Triggered on card enter completion
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 8. Implement tab-specific animations
  - Overview: count-up for .shce-tile-value numbers
  - Queue: slide from x:-24, pulse red/green borders on risk nodes
  - Errors: fade up rows sequentially
  - Knowledge: stagger up table rows with back.out
  - History: slide from x:-16
  - Environment: scale-in with back.out(1.4)
  - Kill repeating tweens on tab deactivation
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3_

- [x] 9. Implement MutationObserver for view and tab detection
  - Watch .view elements for active class (view changes)
  - Watch .shce-panel-section elements for active class (tab changes)
  - Dispatch onViewActivated(id) and onSHCETabActivated(id)
  - startObservers() / stopObservers() lifecycle
  - _Requirements: 13.5_

- [x] 10. Implement settings toggle
  - Pill toggle injected into .sidebar-footer
  - Toggle off: kill all tweens, remove canvas, restore elements
  - Toggle on: re-init for current view
  - localStorage persistence
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

- [x] 11. Final verification
  - GSAP loads without errors in Tauri webview
  - All 13 requirements covered in animations.js
  - Toggle persists across reloads
  - Backend files all parse clean
  - No regressions in main.js functionality
  - _Requirements: All_

## Notes

- All tasks 1–11 have been implemented in `frontend/animations.js`, `frontend/index.html`, and `frontend/style.css`
- GSAP CDN URLs use exact version 3.12.5 with SRI integrity hashes for security
- The animation toggle is injected into the sidebar footer as a pill switch
- MutationObserver provides zero-coupling integration with main.js
- All animations use transform/opacity only for GPU compositing
- ScrollTrigger.batch() handles large card grids without performance degradation
- Graceful degradation: if GSAP CDN fails, the app works exactly as before
