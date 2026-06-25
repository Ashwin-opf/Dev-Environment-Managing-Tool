# Requirements Document

## Introduction

This feature adds GSAP-powered premium animations to the existing SHCE Control Center view in PC Doctor — a Tauri desktop app with a vanilla JS/HTML/CSS frontend. The goal is to enhance the visual experience with scroll-driven reveal animations, staggered card content entrances, hover microinteractions, section-specific thematic effects, and a smooth active navigation indicator — all without rewriting any existing logic. Animations follow a Samsung One UI + Material Design 3 aesthetic: glassmorphism surfaces, 20–24 px corner radii, soft depth shadows, and a dark-mode-first GPU-composited rendering strategy. A settings toggle allows global disable. If GSAP fails to load from CDN, the app continues to function normally without any animations.

---

## Glossary

- **Animation_System**: The GSAP-based animation layer initialized in `frontend/animations.js`
- **GSAP**: GreenSock Animation Platform — the animation library loaded from CDN
- **ScrollTrigger**: GSAP plugin that fires animations when elements enter or exit the scroll viewport
- **SHCE_View**: The `#view-os-adaptation` section of the app, comprising stat tiles, tab bar, and tabbed panel sections
- **SHCE_Card**: Any `.shce-stat-tile`, `.adaptation-panel`, or `.shce-panel-section` element within the SHCE_View
- **Dashboard_Card**: Any `.module-card`, `.driver-card`, or `.resource-tile` element across all views
- **Stagger_Group**: A set of child elements within a card that animate sequentially (title → description → buttons → charts → controls)
- **Scroll_Scene**: A ScrollTrigger instance that manages a single SHCE_Card's enter and exit animation states
- **Nav_Indicator**: The sliding highlight element that tracks the active sidebar navigation item
- **Particle_Canvas**: A `<canvas>` overlay element rendered behind the AI Core tab content
- **Settings_Panel**: The overlay opened by the settings gear button (`#settings-toggle-btn`) in the topbar
- **Animations_Toggle**: A rounded on/off switch inside the Settings_Panel that controls global animation state
- **localStorage_Key**: The key `pc_doctor_animations_enabled` used to persist the animation preference
- **Graceful_Degradation**: The behavior where all SHCE_View content is fully visible and functional when GSAP is absent or animations are disabled

---

## Requirements

---

### Requirement 1: GSAP CDN Loading and Graceful Degradation

**User Story:** As a user, I want the app to load GSAP animations without affecting app stability, so that a CDN failure never breaks PC Doctor's core functionality.

#### Acceptance Criteria

1. THE `index.html` SHALL include a `<script>` tag loading GSAP core from `https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js` after all existing `<script>` tags.
2. THE `index.html` SHALL include a `<script>` tag loading the ScrollTrigger plugin from `https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js` after the GSAP core script tag.
3. THE `index.html` SHALL include a `<script src="animations.js">` tag after the ScrollTrigger script tag and after `main.js`.
4. WHEN GSAP fails to load from CDN, THE Animation_System SHALL skip all animation initialization and leave all elements in their default visible state.
5. IF the global `gsap` object is undefined at initialization time, THEN THE Animation_System SHALL exit silently without throwing any uncaught JavaScript errors.
6. THE Animation_System SHALL wrap all GSAP initialization code in a top-level try/catch block so that any runtime error inside animations.js does not propagate to `main.js` or break existing app functionality.

---

### Requirement 2: Animation Enable/Disable Toggle in Settings

**User Story:** As a user, I want a toggle in the settings panel to turn animations on or off globally, so that I can disable them if I prefer a reduced-motion experience or lower resource use.

#### Acceptance Criteria

1. THE Settings_Panel SHALL contain an Animations_Toggle rendered as a rounded pill-style `<input type="checkbox">` on/off switch with a visible label "Animations".
2. WHEN the Animations_Toggle is turned on, THE Animation_System SHALL set `localStorage.getItem('pc_doctor_animations_enabled')` to the string `'true'`.
3. WHEN the Animations_Toggle is turned off, THE Animation_System SHALL set `localStorage.getItem('pc_doctor_animations_enabled')` to the string `'false'`.
4. WHEN the Settings_Panel is opened, THE Animations_Toggle SHALL reflect the current value of `localStorage.getItem('pc_doctor_animations_enabled')`, defaulting to enabled when the key is absent.
5. WHEN the Animations_Toggle is turned off, THE Animation_System SHALL immediately kill all active GSAP tweens and ScrollTrigger instances and restore all animated elements to their fully visible default state (opacity 1, transform none).
6. WHEN the Animations_Toggle is turned on after being off, THE Animation_System SHALL re-initialize all scroll-based animations and hover listeners for the currently active view.
7. WHILE `localStorage.getItem('pc_doctor_animations_enabled') === 'false'`, THE Animation_System SHALL skip all animation initialization on page load and render all SHCE_View elements at full opacity with no transform applied.
8. THE Animation_System SHALL check the localStorage_Key value once at startup, before registering any GSAP timelines or ScrollTrigger instances.

---

### Requirement 3: Scroll Reveal — Japanese Story Scroll Effect

**User Story:** As a user, I want SHCE section cards to appear with a cinematic scroll-driven reveal, so that the Control Center feels premium and immersive.

#### Acceptance Criteria

1. WHEN the SHCE_View is active and animations are enabled, THE Animation_System SHALL register a Scroll_Scene for every SHCE_Card using GSAP ScrollTrigger with `scroller` set to the SHCE_View's scrollable container.
2. WHEN a SHCE_Card enters the viewport, THE Animation_System SHALL animate the card from `{ opacity: 0, y: 120, scale: 0.96, filter: 'blur(10px)' }` to `{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }` with a duration of `0.8s` and easing `power4.out`.
3. WHEN a SHCE_Card exits the top of the viewport, THE Animation_System SHALL animate the card to `{ opacity: 0.75, scale: 0.97 }` with a duration of `0.4s`.
4. THE Animation_System SHALL configure each Scroll_Scene with `start: 'top 90%'` and `end: 'top 10%'` so that the next section is 10–15 % visible at the viewport bottom before the full reveal triggers (sunrise peek effect).
5. THE Animation_System SHALL only use `transform` and `opacity` CSS properties during scroll animations to maintain GPU compositing and 60 FPS performance.
6. WHEN the SHCE_View is navigated away from, THE Animation_System SHALL call `ScrollTrigger.getAll().forEach(st => st.kill())` to clean up all active Scroll_Scene instances for that view.
7. IF a SHCE_Card is already fully within the viewport when the SHCE_View is first activated, THEN THE Animation_System SHALL play the card's reveal animation immediately without requiring a scroll event.

---

### Requirement 4: Staggered Card Content Animation

**User Story:** As a user, I want each card's content to animate in sequentially, so that reading flow matches the visual reveal and the UI feels intentional rather than abrupt.

#### Acceptance Criteria

1. WHEN a SHCE_Card completes its scroll-reveal entry animation, THE Animation_System SHALL animate the card's Stagger_Group children sequentially using a stagger delay of `0.08s` per item.
2. THE Animation_System SHALL treat the following child selectors as the Stagger_Group order for each SHCE_Card: headings (`h2`, `h3`) first, then descriptive text (`p`, `.feature-desc`), then action buttons (`.action-btn`, `.primary-btn`, `.quiet-btn`), then data visualizations (`.adaptation-progress-block`, `.shce-overview-grid`, table elements), then form controls and inputs last.
3. THE Stagger_Group animation SHALL transition each item from `{ opacity: 0, y: 16 }` to `{ opacity: 1, y: 0 }` with a duration of `0.35s` per item and easing `power2.out`.
4. WHILE animations are disabled, THE Animation_System SHALL not apply any initial hidden states to Stagger_Group children, ensuring all content is immediately readable.

---

### Requirement 5: Dashboard Card Hover Microinteraction

**User Story:** As a user, I want cards to respond to hover with a subtle lift effect, so that interactive elements feel tactile and premium.

#### Acceptance Criteria

1. WHEN the cursor enters a Dashboard_Card, THE Animation_System SHALL animate the card to `{ y: -6, scale: 1.02, boxShadow: '0 20px 60px rgba(0,0,0,0.45), 0 0 0 1px rgba(10,132,255,0.3)' }` over `0.25s` with easing `power2.out`.
2. WHEN the cursor leaves a Dashboard_Card, THE Animation_System SHALL animate the card back to `{ y: 0, scale: 1, boxShadow: '' }` over `0.25s` with easing `power2.inOut`.
3. THE Animation_System SHALL use `gsap.to()` for hover animations and SHALL NOT use CSS `transition` overrides on `.module-card`, `.driver-card`, or `.resource-tile` elements, preserving existing CSS hover styles for non-GSAP contexts.
4. THE Animation_System SHALL attach hover listeners via delegated `mouseenter` and `mouseleave` events on the nearest scrollable container rather than on each card individually, to support dynamically injected cards.
5. WHILE animations are disabled, THE Animation_System SHALL not attach any hover listeners, allowing existing CSS-only hover styles to remain active.

---

### Requirement 6: AI Core Tab — Particle and Metrics Animation

**User Story:** As a user, I want the AI Core / Overview tab to show particle effects and counting metrics when it is active, so that the section communicates "live AI processing" visually.

#### Acceptance Criteria

1. WHEN the SHCE Overview tab (`#shce-section-overview`) becomes active and animations are enabled, THE Animation_System SHALL activate a Particle_Canvas overlay behind the section content displaying 30–50 floating translucent particles.
2. THE Particle_Canvas SHALL animate each particle independently using `requestAnimationFrame`, with each particle following a slow drift path (velocity ≤ 0.5 px/frame in any direction) and an opacity oscillation between `0.1` and `0.4`.
3. WHEN the SHCE Overview tab becomes active, THE Animation_System SHALL animate all numeric value elements matching `.shce-tile-value` from `0` to their current text content value over `1.2s` using `gsap.to()` with easing `power2.out`.
4. WHEN the SHCE Overview tab is deactivated or the SHCE_View is navigated away from, THE Animation_System SHALL cancel the Particle_Canvas `requestAnimationFrame` loop and remove the Particle_Canvas from the DOM.
5. THE Particle_Canvas SHALL be positioned with `position: absolute; inset: 0; pointer-events: none; z-index: 0` so that it never intercepts mouse events on functional UI elements.

---

### Requirement 7: Self-Healing Core Tab — Data Flow and Node Pulse Animation

**User Story:** As a user, I want the Repair Queue tab to show animated data flow lines and pulsing status nodes so that error detection and recovery feel dynamic and communicative.

#### Acceptance Criteria

1. WHEN the SHCE Repair Queue tab (`#shce-section-queue`) becomes active and animations are enabled, THE Animation_System SHALL animate each `.shce-error-log` entry or `.shce-queue-list > *` item with a left-to-right sliding entrance from `{ x: -24, opacity: 0 }` to `{ x: 0, opacity: 1 }` staggered at `0.06s` per item.
2. WHEN an element within `#shce-queue-list` carries a data attribute or class indicating an error state (e.g. `.risk-high`, `[data-risk="high"]`), THE Animation_System SHALL apply a repeating pulse animation to that element's left border or icon using `gsap.to()` with `yoyo: true, repeat: -1` cycling between `rgba(255,59,48,0.6)` and `rgba(255,59,48,0.15)` on a `1.2s` cycle.
3. WHEN an element within `#shce-queue-list` carries a state indicating recovery or resolution (e.g. `.risk-low`, `[data-risk="low"]`), THE Animation_System SHALL apply a repeating glow pulse animation cycling between `rgba(48,209,88,0.5)` and `rgba(48,209,88,0.1)` on a `1.8s` cycle.
4. WHEN the SHCE Repair Queue tab is deactivated, THE Animation_System SHALL kill all repeating pulse tweens associated with that tab to prevent background CPU usage.

---

### Requirement 8: Command Generator Tab — Typewriter and Validation Animation

**User Story:** As a user, I want commands in the Error Monitor tab to appear line by line with a blinking cursor, so that the experience feels like watching the system actively work.

#### Acceptance Criteria

1. WHEN the SHCE Error Monitor tab (`#shce-section-errors`) becomes active and animations are enabled, THE Animation_System SHALL animate each entry row in `#shce-error-log` appearing sequentially from `{ opacity: 0, y: 8 }` to `{ opacity: 1, y: 0 }` staggered at `0.05s` per row.
2. WHEN an error entry row contains a fix command displayed in a `<code>` or monospace element, THE Animation_System SHALL reveal the command text character by character at a rate of 30–40 characters per second using a GSAP text-reveal technique (clip-path or per-character opacity stagger).
3. WHEN a fix entry carries a resolved or validated status, THE Animation_System SHALL play a one-shot checkmark scale animation on the status indicator from `{ scale: 0, opacity: 0 }` to `{ scale: 1, opacity: 1 }` over `0.3s` with easing `back.out(1.7)`.
4. WHEN the SHCE Error Monitor tab is deactivated, THE Animation_System SHALL kill all active typewriter and checkmark tweens.

---

### Requirement 9: RAG Knowledge Base Tab — Card Float and Search Cascade Animation

**User Story:** As a user, I want the Knowledge Base tab to feel like a living document where entries float in and search results cascade gracefully, so that the data exploration experience is engaging.

#### Acceptance Criteria

1. WHEN the SHCE Knowledge Base tab (`#shce-section-knowledge`) becomes active and animations are enabled, THE Animation_System SHALL animate each row in `#shce-kb-body` from `{ opacity: 0, y: 20 }` to `{ opacity: 1, y: 0 }` staggered at `0.04s` per row with easing `power2.out`.
2. WHEN the user types into `#shce-kb-search` and the table rows are filtered, THE Animation_System SHALL animate newly visible rows in from `{ opacity: 0, scale: 0.97 }` to `{ opacity: 1, scale: 1 }` over `0.2s` staggered at `0.03s` per row.
3. WHEN the SHCE Knowledge Base tab is deactivated, THE Animation_System SHALL kill all active stagger tweens for that tab.

---

### Requirement 10: Navigation Indicator — Sliding Active Highlight

**User Story:** As a user, I want the active sidebar navigation item to have a smoothly sliding highlight indicator, so that navigation feels fluid and premium rather than abrupt.

#### Acceptance Criteria

1. THE Animation_System SHALL create a single `<div class="nav-slide-indicator">` element injected once into `.sidebar-nav` at initialization, absolutely positioned with `pointer-events: none`.
2. WHEN the active navigation item changes, THE Animation_System SHALL animate the Nav_Indicator's `top` and `height` properties using `gsap.to()` with a spring-like easing (`elastic.out(1, 0.75)`) over `0.45s` to match the bounding rect of the newly active `.nav-item`.
3. WHEN the active navigation icon receives the `.active` class, THE Animation_System SHALL animate the icon's `filter` property to `drop-shadow(0 0 6px rgba(10,132,255,0.7))` over `0.2s`.
4. WHEN a navigation item loses the `.active` class, THE Animation_System SHALL animate the icon's `filter` back to `drop-shadow(0 0 0px transparent)` over `0.2s`.
5. WHILE animations are disabled, THE Animation_System SHALL not inject the Nav_Indicator element and SHALL not apply any icon glow styles.

---

### Requirement 11: Background Effects — Ambient Particles and Gradient Movement

**User Story:** As a user, I want the app background to have subtle ambient motion so that the interface feels alive without being distracting.

#### Acceptance Criteria

1. WHEN the app initializes with animations enabled, THE Animation_System SHALL inject a `<canvas id="bg-particle-canvas">` element as the first child of `<body>` with `position: fixed; inset: 0; pointer-events: none; z-index: 0; opacity: 0.35`.
2. THE bg-particle-canvas SHALL render 20–35 floating particles using `requestAnimationFrame`, each with a random drift velocity ≤ 0.3 px/frame and a random radius between 1 px and 3 px, using colors sampled from the app's accent palette (`#0a84ff`, `#bf5af2`, `#5ac8fa`).
3. THE Animation_System SHALL animate the `body` background-position of the existing radial gradient mesh using `gsap.to()` with `duration: 12, repeat: -1, yoyo: true` producing a slow ambient gradient shift that covers no more than 15 % of the viewport in any axis.
4. WHEN animations are disabled at runtime (toggle turned off), THE Animation_System SHALL cancel the bg-particle-canvas `requestAnimationFrame` loop and remove the canvas element from the DOM.
5. THE bg-particle-canvas SHALL never cause layout reflow; all drawing SHALL occur via the Canvas 2D API only.

---

### Requirement 12: Performance and Rendering Constraints

**User Story:** As a developer, I want the animation system to stay within strict GPU rendering guidelines, so that the app maintains 60 FPS at all supported resolutions from 1366×768 to 4K.

#### Acceptance Criteria

1. THE Animation_System SHALL only animate CSS properties `transform` (translateX, translateY, scale, rotate) and `opacity` in any GSAP tween that is part of a scroll or continuous animation, to avoid triggering layout or paint.
2. THE Animation_System SHALL apply `will-change: transform, opacity` to any element before its scroll-reveal animation begins and SHALL remove `will-change` after the animation completes by setting it back to `auto`.
3. THE Animation_System SHALL use `gsap.set()` to set initial hidden states on SHCE_Cards at SHCE_View activation time, not at page load, to avoid invisible-content flash for non-SHCE views.
4. WHEN more than 60 SHCE_Cards are present in the DOM simultaneously, THE Animation_System SHALL batch ScrollTrigger registration using `ScrollTrigger.batch()` rather than individual `ScrollTrigger.create()` calls.
5. THE Animation_System SHALL not use CSS `filter: blur()` on elements that are inside a `will-change: transform` ancestor, as this creates a new stacking context and degrades compositing. Blur animations SHALL only be applied directly to top-level SHCE_Card elements.
6. THE Animation_System SHALL set `gsap.config({ force3D: true })` at initialization to ensure all tween transforms are hardware-accelerated via `translate3d`.
7. WHEN the GSAP ticker detects dropped frames (frame delta > 33 ms), THE Animation_System SHALL log a warning to `console.warn` with the prefix `[PC Doctor Animations]` and reduce particle count by 50 % for the remainder of the session.

---

### Requirement 13: Animation Initialization Architecture

**User Story:** As a developer, I want `animations.js` to be self-contained and initialize only after the DOM is ready, so that it integrates cleanly with the existing `main.js` without tight coupling.

#### Acceptance Criteria

1. THE `animations.js` file SHALL export no functions to global scope except `window.PCDoctorAnimations` which SHALL be an object with two public methods: `init()` and `destroy()`.
2. WHEN `animations.js` is loaded, THE Animation_System SHALL call `window.PCDoctorAnimations.init()` inside a `DOMContentLoaded` listener if `localStorage.getItem('pc_doctor_animations_enabled') !== 'false'`.
3. THE `PCDoctorAnimations.destroy()` method SHALL kill all GSAP tweens, kill all ScrollTrigger instances, remove the bg-particle-canvas element, remove the nav-slide-indicator element, and cancel all `requestAnimationFrame` loops managed by the Animation_System.
4. THE Animation_System SHALL register GSAP's ScrollTrigger plugin via `gsap.registerPlugin(ScrollTrigger)` exactly once at the top level of `animations.js`.
5. WHEN `main.js` calls a view navigation function (e.g. `switchSHCETab`, show/hide view logic), THE Animation_System SHALL observe DOM mutations via `MutationObserver` on `.view.active` and `.shce-panel-section.active` to detect view changes and initialize or kill the relevant animations, without requiring any changes to `main.js`.
6. THE Animation_System SHALL set `gsap.config({ force3D: true })` and `ScrollTrigger.config({ limitCallbacks: true })` at initialization to maximize rendering performance.
