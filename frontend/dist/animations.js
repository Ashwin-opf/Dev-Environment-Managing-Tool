/**
 * PC Doctor — Global UI/UX & Animation System (Reverted)
 * ====================================================
 * Restores native scrolling performance and instant view switches.
 */

(function () {
  'use strict';

  const PCDoctorAnimations = {
    init: () => {
      console.log('[PC Doctor Animations] Minimal animation system active. Standard browser scrolling and instant transitions.');
    },
    destroy: () => {},
    isEnabled: () => false,
    setEnabled: () => {},
    setIntensity: () => {},
    setPerfMode: () => {},
    animateViewTransition: (name, callback) => {
      // Execute the view switch immediately without transition delay/blur
      callback();
    }
  };

  window.PCDoctorAnimations = PCDoctorAnimations;

  // Auto-init
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => PCDoctorAnimations.init());
  } else {
    setTimeout(() => PCDoctorAnimations.init(), 10);
  }
})();
