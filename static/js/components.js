/**
 * CADPrice — Alpine.js component definitions.
 *
 * This file is loaded BEFORE Alpine's CDN script (which has `defer`),
 * so `document.addEventListener('alpine:init', ...)` ensures registration
 * happens at the right moment.
 */

document.addEventListener("alpine:init", () => {
  /**
   * Flash message component.
   * Auto-dismisses after `duration` ms; can also be dismissed manually.
   */
  Alpine.data("flash", () => ({
    show: true,
    duration: 5000,

    init() {
      this._timeout = setTimeout(() => this.dismiss(), this.duration);
    },

    dismiss() {
      clearTimeout(this._timeout);
      this.show = false;
    },
  }));
});
