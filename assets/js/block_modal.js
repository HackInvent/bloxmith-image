/**
 * Role: Mounts the Image block modal frontend.
 * File Name: block_modal.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-06-10
 */

(function () {
  "use strict";

  const registry = (window.CWBlockUiBlocks = window.CWBlockUiBlocks || {});

  registry.image = {
    /**
     * Mark the Image modal as block-owned while generic fields and Apply stay
     * handled by the framework modal API.
     *
     * @param {HTMLElement} root - Mounted Image modal root.
     */
    mount(root) {
      if (root instanceof HTMLElement) {
        root.dataset.imageModalMounted = "true";
      }
    },
  };
})();
