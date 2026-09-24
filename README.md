# Image Block

<!-- block-metadata:start -->
[![Block version: 0.1.0](https://img.shields.io/badge/block-0.1.0-blue)](model.json)
[![BloxSmith compatibility: 1.0.9](https://img.shields.io/badge/BloxSmith-1.0.9-brightgreen)](compatibility.json)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Verified BloxSmith versions: **1.0.9** (bundled-block tests; see [test evidence](compatibility.json)).
<!-- block-metadata:end -->


## Role

`image` generates an image from an instruction and emits the exported image path.

## Files

- `block.py`: image-generation command orchestration, process lifecycle, generated-file discovery, export copying, and runtime outputs.
- `model.json`: instruction input, image output, and generation config.
- `inspector_panel.html`: image inspector UI.
- `block_modal.html`: autonomous modal for image generation settings and runtime state.
- `assets/js/block_modal.js`: modal-owned mount hook used by the framework to keep the modal stable during polling.
- `node_card.html`: block-owned canvas card body.

## Ports

- Inputs:
  - `instruction` (`id: 1`): required image prompt; accepts `message/*`.
- Outputs:
  - `image` (`id: 1`): emits `image/path`, `file/path`, and `message/*`.

## Configuration

- `image_model`: model used for image generation.
- `image_effort`: reasoning/generation effort.
- `image_sandbox`: sandbox mode passed to the generation command.
- `image_timeout_sec`: maximum generation duration.

Static block configuration takes precedence over block-owned environment
fallbacks. The supported fallbacks are `BLOXSMITH_IMAGE_CODEX_MODEL` (then
`BLOXSMITH_IMAGE_MODEL`), `BLOXSMITH_IMAGE_EFFORT`,
`BLOXSMITH_IMAGE_SANDBOX`, and `BLOXSMITH_IMAGE_TIMEOUT_SEC`. `CODEX_HOME`
selects the Codex data directory used to locate `generated_images`.

## Runtime Behavior

`execute_runtime()` builds a generation prompt, launches the image-capable Codex command, waits for generated files, copies the selected image to `exports/images/`, and emits the exported path.

The block supports pause/cancel control, process registration, usage recording, timeout handling through runtime services, and deterministic closure of the child process output stream after every attempt.

## Example

Connect a text instruction such as `A realistic product photo of a blue notebook on a desk` to the `instruction` input. At runtime, the block asks Codex to generate an image, copies the selected generated file under `exports/images/`, and emits the absolute image path.

## UI Behavior

The inspector renders model and effort controls. Model and effort changes are kept pending while edited and are persisted through the GraphController only when the user clicks **Apply**. Sandbox and timeout are runtime configuration fields and remain documented in the block config.

The modal declares `data-block-runtime-refresh="autonomous"`; its open surface is not replaced by runtime polling while the user is editing or inspecting the image block.

## Editor Display

The canvas card is rendered by this block through `node_card.html`. It shows the configured model, effort, and latest output preview while the shared editor shell keeps ports, dragging, status, and graph links generic.

## Limits

The block depends on the local `codex` CLI and image generation support. If no generated image file is found under `$CODEX_HOME/generated_images`, execution fails with an explicit error. It emits a path, not inline image bytes.

## Modal

`block_modal.html` is owned by this block and rendered by the generic modal contract. It shows block state and lets users edit supported title/config fields through generic bindings.

## Maintenance Notes

Keep image file discovery and export naming inside this block. Shared lifecycle services may be injected, but image-specific publication rules belong here.

## Compatibility policy

[compatibility.json](compatibility.json) records HackInvent's verified BloxSmith versions and test evidence. Only the versions listed above have been verified, using the block-owned suites in a **bundled-block test installation**. This is not a certification of managed-package installation, every browser/OS, or live provider availability. Other framework versions are unverified, not necessarily incompatible.

The block-version badge follows `model.json`, not a published Git tag. `unversioned` means that no block release version is declared; no number is inferred from the framework version. The framework still uses `model.json` for its runtime/install contract; the tester-owned JSON does not replace it. Official integration tests run in the private `bloxmith-blocs` workspace. Test helpers and the proprietary framework are not bundled in this public block repository.

## Properties ergonomics

Modal and inspector styles are owned by this package and scoped to its exact
release. Forms adapt to narrow panels, checkboxes stay beside their labels, and
long values do not widen the inspector. Existing labels are associated with
controls; keyboard navigation complements the block’s own tab handlers.
These presentation helpers do not change port bindings, authored settings,
runtime behavior or the block’s original surface cleanup.
