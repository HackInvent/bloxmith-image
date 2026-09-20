/**
 * Role: Mounts the Image block modal frontend.
 * File Name: block_modal.js
 * Author: Alexandre EL
 * Email: alex@hackinvent.com
 * Created Date: 2026-06-10
 */

/**
 * Mark the Image modal as block-owned while generic fields and Apply stay
 * handled by the framework modal API.
 *
 * @param {HTMLElement} root - Mounted Image modal root.
 */
export function mount(root) {
  if (root instanceof HTMLElement) {
    root.dataset.imageModalMounted = "true";
  }
}
