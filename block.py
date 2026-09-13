# -----------------------------------------------------------------------------
# Role: Implements the image block runtime and UI contract.
# File Name: block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2024-06-16
# -----------------------------------------------------------------------------

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
import json
import os
import re
import shutil
import subprocess
import time

from bloxsmith_app.block_api import (
    BlockDefinition,
    BlockRuntimeContext,
    BlockRuntimeOutput,
    BlockRuntimeResult,
    CODEX_USAGE_KEYS,
    configured_runs_dir,
    format_codex_usage_log,
    IMAGE_PATH,
    normalize_codex_usage,
    parse_codex_stdout_line,
    render_inspector_template,
    render_node_card_template,
    TEXT_PLAIN,
    toml_string,
)


IMAGE_NODE_PROMPT_TEMPLATE = (
    "Ton seul rôle est de générer des images, rien d'autre, "
    "en respectant l'instruction suivante: {instruction}\n\n"
    "Utilise l'outil de génération d'image disponible. "
    "Ne crée pas de fichier dans le workspace, ne copie rien, "
    "et ne réponds pas par une description textuelle."
)
DEFAULT_IMAGE_CODEX_MODEL = "gpt-5.5"
DEFAULT_IMAGE_CODEX_EFFORT = "low"
DEFAULT_IMAGE_SANDBOX = "workspace-write"
DEFAULT_IMAGE_TIMEOUT_SEC = 180.0
CODEX_GENERATED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


# Functional behavior:
# FB1 - Build an image-generation Codex prompt from the configured instruction and optional input data.
# FB2 - Execute Codex CLI for image generation and ignore global text-output Codex policy.
# FB3 - Capture thread_id and token usage from Codex JSON events.
# FB4 - Discover generated image assets, copy the selected image into exports/images, and emit its path.
# FB5 - Surface empty instructions, CLI failures, timeouts, and missing images as block failures.
class ImageBlock(BlockDefinition):
    """Autonomous block implementation for `ImageBlock`."""
    kind = "image"

    def ui_assets(self, surface: str = "modal") -> list[dict[str, str]]:
        """Return block-owned frontend assets for the requested UI surface.

        Args:
            surface: UI surface requesting assets.
        """
        if surface == "modal":
            return [{"kind": "js", "path": "assets/js/block_modal.js"}]
        return []

    def render_node_card(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the Image canvas card body from the block-owned template.

        Args:
            node: Serialized image node whose config contains generation settings.
            payload: Optional server/UI rendering payload.

        Returns:
            Block UI payload used by the generic canvas shell.
        """

        config = self._ui_config(node)
        preview = str(node.get("output") or "instruction -> image")
        return render_node_card_template(
            block=self,
            node=node,
            node_classes=["image-node"],
            replacements={
                "title": node.get("title") or self.default_title(),
                "preview": self._truncate(preview, 56),
                "model": self._image_codex_model(config),
                "effort": self._normalize_codex_effort(config.get("image_effort")),
            },
        )

    def render_inspector_panel(self, *, node: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render the block-owned inspector panel HTML for the selected node.

        Args:
            node: Serialized graph node handled by the block.
            payload: Optional UI or runtime payload provided by the framework.
        """
        model = self._image_codex_model(self._ui_config(node))
        effort = self._normalize_codex_effort(self._ui_config(node).get("image_effort"))
        template = (self.directory / "inspector_panel.html").read_text(encoding="utf-8")
        html = render_inspector_template(
            template=(
                template
                .replace("{{ model_options }}", self._select_options(["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.2"], model))
                .replace("{{ effort_options }}", self._select_options(["low", "medium", "high", "xhigh"], effort, labels={"low": "Bas", "medium": "Moyen", "high": "Haut", "xhigh": "Élevé"}))
            ),
            node={**node, "type": self.kind, "kind": self.kind},
            payload=payload,
        )
        return {"html": html, "context": {"node_id": str(node.get("id") or ""), "full_panel": True}}

    def _ui_config(self, node: dict[str, Any]) -> dict[str, Any]:
        """Provide internal ImageBlock behavior for `_ui_config`.

        Args:
            node: Serialized graph node handled by the block.
        """
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {
            "image_model": config.get("image_model", DEFAULT_IMAGE_CODEX_MODEL),
            "image_effort": config.get("image_effort", DEFAULT_IMAGE_CODEX_EFFORT),
        }

    def _select_options(self, values: list[str], selected: str, labels: dict[str, str] | None = None) -> str:
        """Provide internal ImageBlock behavior for `_select_options`.

        Args:
            values: Values value used by this block helper.
            selected: Selected value used by this block helper.
            labels: Labels value used by this block helper.
        """
        labels = labels or {}
        return "\n".join(
            f'<option value="{escape(value)}"{" selected" if value == selected else ""}>{escape(labels.get(value, value))}</option>'
            for value in values
        )

    def _truncate(self, value: str, max_length: int) -> str:
        """Return a compact one-line image preview for the canvas card."""

        text = str(value or "").replace("\n", " ").strip()
        return text if len(text) <= max_length else f"{text[: max_length - 1]}..."

    def execute_runtime(self, context: BlockRuntimeContext) -> BlockRuntimeResult:
        """Execute the block through the generic runtime context and return runtime outputs.

        Args:
            context: Generic runtime context injected by the execution engine.
        """
        instruction = str(
            context.input_value("instruction")
            or context.input_value("1")
            or context.input_message
            or ""
        ).strip()
        if not instruction:
            return BlockRuntimeResult(
                status="failed",
                error="instruction d'entree vide.",
                exit_code=1,
                last_message="instruction d'entree vide.",
                worker_received="-",
                logs=[f"[image-error] {context.node_id}: instruction d'entree vide."],
            )

        logs: list[str] = []
        self._emit_log(context, logs, "[image] Consigne globale Codex ignoree pour ce bloc.")
        image_result = self._execute_generation(context, instruction, logs)
        if image_result.get("status") == "cancelled":
            return BlockRuntimeResult(status="cancelled", worker_received=instruction)

        exit_code = int(image_result.get("exit_code") or 0)
        port_id = int(image_result.get("port_id") or 1)
        port_name = str(image_result.get("port_name") or "image")
        if exit_code != 0:
            error = str(image_result.get("error") or "generation image echouee")
            self._emit_log(context, logs, f"[image-error] {context.node_id}: {error}.")
            return BlockRuntimeResult(
                status="failed",
                outputs=[],
                logs=logs,
                error=error,
                exit_code=exit_code or 1,
                last_message=error,
                worker_received=instruction,
                metadata=self._result_metadata(image_result, content_type=TEXT_PLAIN),
            )

        value = str(image_result.get("value") or image_result.get("last_message") or "")
        self._emit_log(context, logs, f"[done] Image {context.node_id} generee: {value}")
        return BlockRuntimeResult(
            status="success",
            outputs=[
                BlockRuntimeOutput(
                    port_id=port_id,
                    port_name=port_name,
                    value=value,
                    content_type=IMAGE_PATH,
                    status="success",
                    exit_code=0,
                    metadata=dict(image_result),
                )
            ],
            logs=logs,
            last_message=value,
            content_type=IMAGE_PATH,
            worker_received=value or instruction,
            metadata=self._result_metadata(image_result, content_type=IMAGE_PATH),
        )

    def _execute_generation(
        self,
        context: BlockRuntimeContext,
        instruction: str,
        logs: list[str],
    ) -> dict[str, Any]:
        """Provide internal ImageBlock behavior for `_execute_generation`.

        Args:
            context: Generic runtime context injected by the execution engine.
            instruction: Instruction text configured for the target output.
            logs: Logs value used by this block helper.
        """
        if self._cancel_requested(context):
            return {"status": "cancelled", "port_id": 1}
        if not self._wait_if_paused(context):
            return {"status": "cancelled", "port_id": 1}

        output_port = self._find_output_port(context, 1)
        port_id = int(getattr(output_port, "id", 1) or 1)
        port_name = str(getattr(output_port, "name", "") or "image")
        run_dir = (context.run_dir or (configured_runs_dir(context.root_dir) / context.run_id)).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        output_file = run_dir / f"{context.node_id}_image_last_message.txt"
        prompt = self._build_image_generation_prompt(instruction)
        started_at = time.time()

        model = self._image_codex_model(context.config)
        effort = self._normalize_codex_effort(
            (context.config or {}).get("image_effort")
            or (context.config or {}).get("effort")
            or os.getenv("BLOXSMITH_IMAGE_EFFORT")
            or DEFAULT_IMAGE_CODEX_EFFORT
        )
        sandbox_mode = self._image_sandbox_mode(context.config)
        timeout_sec = self._normalize_positive_float(
            (context.config or {}).get("image_timeout_sec") or os.getenv("BLOXSMITH_IMAGE_TIMEOUT_SEC"),
            default=DEFAULT_IMAGE_TIMEOUT_SEC,
        )
        codex_home = self._codex_home()
        generated_root = codex_home / "generated_images"
        before_images = self._snapshot_generated_images(generated_root)
        self._emit_log(
            context,
            logs,
            f"[image-codex] {context.node_id}: codex exec model={model} effort={effort} sandbox={sandbox_mode}",
        )

        slot_acquired = self._acquire_process_slot(context)
        if not slot_acquired:
            return {"status": "cancelled", "port_id": port_id, "port_name": port_name}

        usage: dict[str, int] = normalize_codex_usage(None)
        exit_code = 1
        image_error = ""
        thread_id = ""
        image_path: Path | None = None
        command = self._build_image_codex_command(
            root_dir=context.root_dir,
            prompt=prompt,
            output_file=output_file,
            model=model,
            effort=effort,
            sandbox_mode=sandbox_mode,
        )
        self._emit_log(context, logs, f"[cmd] {' '.join(command)}")
        process: subprocess.Popen[str] | None = None
        process_key = str(context.services.get("process_key") or f"{context.node_id}:image")
        try:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(context.root_dir),
                    env=os.environ.copy(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                self._register_process(context, process_key, process)
                if self._pause_requested(context):
                    self._pause_process(context, process)

                assert process.stdout is not None
                for raw_line in process.stdout:
                    stripped_line = raw_line.rstrip("\n")
                    thread_id = thread_id or self._extract_codex_thread_id(stripped_line)
                    stdout_event = parse_codex_stdout_line(stripped_line)
                    for log_line in stdout_event.log_lines:
                        self._emit_log(context, logs, log_line)
                    if stdout_event.usage:
                        recorded_usage = self._record_codex_usage(context, stdout_event.usage)
                        usage = {
                            key: usage.get(key, 0) + recorded_usage.get(key, 0)
                            for key in (*CODEX_USAGE_KEYS, "total_tokens")
                        }
                        if recorded_usage.get("total_tokens", 0) > 0:
                            self._emit_log(context, logs, format_codex_usage_log(recorded_usage))

                    if self._cancel_requested(context):
                        self._terminate_process(context, process)
                        break

                try:
                    exit_code = process.wait(timeout=max(1.0, timeout_sec))
                except subprocess.TimeoutExpired:
                    image_error = f"Timeout Codex image apres {timeout_sec:g}s"
                    self._terminate_process(context, process)
                    exit_code = 1
                if exit_code == 0:
                    image_path = self._find_generated_image(
                        generated_root,
                        thread_id=thread_id,
                        before_images=before_images,
                    )
            except (OSError, RuntimeError) as exc:
                image_error = str(exc)
        finally:
            if process is not None:
                if process.stdout is not None and not process.stdout.closed:
                    process.stdout.close()
                self._unregister_process(context, process_key, process)
            self._release_process_slot(context)

        if self._cancel_requested(context):
            return {"status": "cancelled", "port_id": port_id, "port_name": port_name}

        if exit_code != 0 or image_path is None:
            if not image_error and exit_code == 0:
                expected_dir = generated_root / self._safe_path_segment(thread_id) if thread_id else generated_root
                image_error = f"Aucune image generee detectee dans {expected_dir}"
            return {
                "status": "failed",
                "port_id": port_id,
                "port_name": port_name,
                "output_file": str(output_file),
                "last_message": "",
                "exit_code": exit_code or 1,
                "usage": usage,
                "error": image_error or "generation image Codex echouee",
                "thread_id": thread_id,
            }

        elapsed = round(max(0.0, time.time() - started_at), 3)
        try:
            copied_image_path = self._copy_generated_image_to_exports(
                context.root_dir,
                image_path,
                run_id=context.run_id,
                node_id=context.node_id,
            )
        except OSError as exc:
            return {
                "status": "failed",
                "port_id": port_id,
                "port_name": port_name,
                "output_file": str(output_file),
                "last_message": "",
                "exit_code": 1,
                "usage": usage,
                "error": f"Image generee mais copie impossible: {exc}",
                "thread_id": thread_id,
                "source_file": str(image_path),
            }

        absolute_path = str(copied_image_path.resolve())
        output_file.write_text(absolute_path + "\n", encoding="utf-8")
        self._emit_log(
            context,
            logs,
            f"[image] {context.node_id}: image generee en {elapsed}s vers {absolute_path}.",
        )
        return {
            "status": "success",
            "port_id": port_id,
            "port_name": port_name,
            "output_file": absolute_path,
            "last_message": absolute_path,
            "value": absolute_path,
            "content_type": IMAGE_PATH,
            "source_file": str(image_path),
            "thread_id": thread_id,
            "exit_code": 0,
            "usage": usage,
        }

    def _result_metadata(self, image_result: dict[str, Any], *, content_type: str) -> dict[str, Any]:
        """Provide internal ImageBlock behavior for `_result_metadata`.

        Args:
            image_result: Image result value used by this block helper.
            content_type: Content type value used by this block helper.
        """
        return {
            "output_file": str(image_result.get("output_file") or ""),
            "image_source_file": str(image_result.get("source_file") or ""),
            "content_type": content_type,
            "usage": dict(image_result.get("usage") or {}),
            "thread_id": str(image_result.get("thread_id") or ""),
        }

    def _emit_log(self, context: BlockRuntimeContext, logs: list[str], line: str) -> None:
        """Emit a runtime log or event through the injected context.

        Args:
            context: Generic runtime context injected by the execution engine.
            logs: Logs value used by this block helper.
            line: Line value used by this block helper.
        """
        live_logger = context.services.get("append_log")
        if callable(live_logger):
            live_logger(str(line))
            return
        logs.append(str(line))

    def _cancel_requested(self, context: BlockRuntimeContext) -> bool:
        """Provide internal ImageBlock behavior for `_cancel_requested`.

        Args:
            context: Generic runtime context injected by the execution engine.
        """
        callback = context.services.get("cancel_requested")
        return bool(callback()) if callable(callback) else False

    def _pause_requested(self, context: BlockRuntimeContext) -> bool:
        """Provide internal ImageBlock behavior for `_pause_requested`.

        Args:
            context: Generic runtime context injected by the execution engine.
        """
        callback = context.services.get("pause_requested")
        return bool(callback()) if callable(callback) else False

    def _wait_if_paused(self, context: BlockRuntimeContext) -> bool:
        """Wait for runtime state required before continuing execution.

        Args:
            context: Generic runtime context injected by the execution engine.
        """
        callback = context.services.get("wait_if_paused")
        return bool(callback()) if callable(callback) else True

    def _pause_process(self, context: BlockRuntimeContext, process: subprocess.Popen[str]) -> None:
        """Provide internal ImageBlock behavior for `_pause_process`.

        Args:
            context: Generic runtime context injected by the execution engine.
            process: Process value used by this block helper.
        """
        callback = context.services.get("pause_process")
        if callable(callback):
            callback(process)

    def _terminate_process(self, context: BlockRuntimeContext, process: subprocess.Popen[str]) -> None:
        """Provide internal ImageBlock behavior for `_terminate_process`.

        Args:
            context: Generic runtime context injected by the execution engine.
            process: Process value used by this block helper.
        """
        callback = context.services.get("terminate_process")
        if callable(callback):
            callback(process)
            return
        try:
            process.terminate()
        except OSError:
            pass

    def _register_process(self, context: BlockRuntimeContext, process_key: str, process: subprocess.Popen[str]) -> None:
        """Track a child process while the block is running.

        Args:
            context: Generic runtime context injected by the execution engine.
            process_key: Process key value used by this block helper.
            process: Process value used by this block helper.
        """
        callback = context.services.get("register_process")
        if callable(callback):
            callback(process_key, process)

    def _unregister_process(self, context: BlockRuntimeContext, process_key: str, process: subprocess.Popen[str]) -> None:
        """Track a child process while the block is running.

        Args:
            context: Generic runtime context injected by the execution engine.
            process_key: Process key value used by this block helper.
            process: Process value used by this block helper.
        """
        callback = context.services.get("unregister_process")
        if callable(callback):
            callback(process_key, process)

    def _record_codex_usage(self, context: BlockRuntimeContext, usage: Any) -> dict[str, int]:
        """Record runtime metadata produced by this block execution.

        Args:
            context: Generic runtime context injected by the execution engine.
            usage: Usage value used by this block helper.
        """
        callback = context.services.get("record_codex_usage")
        if callable(callback):
            recorded = callback(usage)
            return normalize_codex_usage(recorded)
        return normalize_codex_usage(usage)

    def _acquire_process_slot(self, context: BlockRuntimeContext) -> bool:
        """Coordinate access to a shared runtime resource for this block.

        Args:
            context: Generic runtime context injected by the execution engine.
        """
        slot = context.services.get("codex_process_slots")
        if slot is None:
            context.services["_image_slot_acquired"] = False
            return True
        while not self._cancel_requested(context):
            if not self._wait_if_paused(context):
                context.services["_image_slot_acquired"] = False
                return False
            acquire = getattr(slot, "acquire", None)
            if callable(acquire) and acquire(timeout=0.2):
                context.services["_image_slot_acquired"] = True
                return True
        context.services["_image_slot_acquired"] = False
        return False

    def _release_process_slot(self, context: BlockRuntimeContext) -> None:
        """Coordinate access to a shared runtime resource for this block.

        Args:
            context: Generic runtime context injected by the execution engine.
        """
        if not context.services.get("_image_slot_acquired"):
            return
        release = getattr(context.services.get("codex_process_slots"), "release", None)
        if callable(release):
            release()
        context.services["_image_slot_acquired"] = False

    def _find_output_port(self, context: BlockRuntimeContext, port_id: int) -> Any:
        """Find a matching runtime or graph element for this block.

        Args:
            context: Generic runtime context injected by the execution engine.
            port_id: Numeric port identifier.
        """
        for port in context.output_ports:
            if int(getattr(port, "id", 0) or 0) == int(port_id):
                return port
        return context.output_ports[0] if context.output_ports else None

    def _build_image_generation_prompt(self, instruction: str) -> str:
        """Build a derived runtime value used by this block.

        Args:
            instruction: Instruction text configured for the target output.
        """
        return IMAGE_NODE_PROMPT_TEMPLATE.format(instruction=str(instruction or "").strip())

    def _build_image_codex_command(
        self,
        *,
        root_dir: Path,
        prompt: str,
        model: str,
        output_file: Path,
        effort: str,
        sandbox_mode: str,
    ) -> list[str]:
        """Build a derived runtime value used by this block.

        Args:
            root_dir: Directory path used by the block runtime.
            prompt: Prompt text sent to the underlying model or CLI.
            model: Model value used by this block helper.
            output_file: Output file value used by this block helper.
            effort: Effort value used by this block helper.
            sandbox_mode: Sandbox mode value used by this block helper.
        """
        return [
            "codex",
            "exec",
            "--json",
            "-C",
            str(root_dir),
            "--sandbox",
            sandbox_mode,
            "--skip-git-repo-check",
            "--ignore-rules",
            "--output-last-message",
            str(output_file),
            "--model",
            model,
            "-c",
            f"model_reasoning_effort={toml_string(effort)}",
            "-c",
            f"approval_policy={toml_string('never')}",
            prompt,
        ]

    def _image_codex_model(self, config: dict[str, Any]) -> str:
        """Provide internal ImageBlock behavior for `_image_codex_model`.

        Args:
            config: Raw or normalized block configuration.
        """
        raw_model = (
            (config or {}).get("image_model")
            or (config or {}).get("model")
            or os.getenv("BLOXSMITH_IMAGE_CODEX_MODEL")
            or os.getenv("BLOXSMITH_IMAGE_MODEL")
            or DEFAULT_IMAGE_CODEX_MODEL
        )
        model = str(raw_model or "").strip()
        if model.startswith("gpt-image"):
            return DEFAULT_IMAGE_CODEX_MODEL
        return model or DEFAULT_IMAGE_CODEX_MODEL

    def _image_sandbox_mode(self, config: dict[str, Any]) -> str:
        """Provide internal ImageBlock behavior for `_image_sandbox_mode`.

        Args:
            config: Raw or normalized block configuration.
        """
        raw_mode = (config or {}).get("image_sandbox") or os.getenv("BLOXSMITH_IMAGE_SANDBOX") or DEFAULT_IMAGE_SANDBOX
        mode = str(raw_mode or DEFAULT_IMAGE_SANDBOX).strip()
        if mode in {"read-only", "workspace-write", "danger-full-access"}:
            return mode
        return DEFAULT_IMAGE_SANDBOX

    def _normalize_codex_effort(self, raw_value: Any) -> str:
        """Normalize a raw value into the format expected by the block.

        Args:
            raw_value: Raw value received from configuration or runtime input.
        """
        effort = str(raw_value or DEFAULT_IMAGE_CODEX_EFFORT).strip().lower()
        return effort if effort in {"low", "medium", "high", "xhigh"} else DEFAULT_IMAGE_CODEX_EFFORT

    def _codex_home(self) -> Path:
        """Provide internal ImageBlock behavior for `_codex_home`."""
        return Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex")).expanduser()

    def _extract_codex_thread_id(self, raw_line: str) -> str:
        """Provide internal ImageBlock behavior for `_extract_codex_thread_id`.

        Args:
            raw_line: Raw value received from configuration or runtime input.
        """
        stripped = str(raw_line or "").strip()
        if not stripped.startswith("{"):
            return ""
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, dict) or payload.get("type") != "thread.started":
            return ""
        return str(payload.get("thread_id") or "").strip()

    def _snapshot_generated_images(self, generated_root: Path) -> set[Path]:
        """Provide internal ImageBlock behavior for `_snapshot_generated_images`.

        Args:
            generated_root: Generated root value used by this block helper.
        """
        if not generated_root.exists():
            return set()
        return set(self._iter_generated_image_files(generated_root))

    def _iter_generated_image_files(self, root: Path) -> list[Path]:
        """Provide internal ImageBlock behavior for `_iter_generated_image_files`.

        Args:
            root: Mounted UI root element or repository root depending on the caller.
        """
        try:
            return [
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in CODEX_GENERATED_IMAGE_EXTENSIONS
            ]
        except OSError:
            return []

    def _find_generated_image(
        self,
        generated_root: Path,
        *,
        thread_id: str,
        before_images: set[Path],
    ) -> Path | None:
        """Find a matching runtime or graph element for this block.

        Args:
            generated_root: Generated root value used by this block helper.
            thread_id: Identifier used to select a graph, port, output, or runtime object.
            before_images: Before images value used by this block helper.
        """
        deadline = time.time() + 3.0
        while True:
            candidates: list[Path] = []
            if thread_id:
                candidates.extend(self._iter_generated_image_files(generated_root / self._safe_path_segment(thread_id)))
            if not candidates:
                candidates.extend(path for path in self._iter_generated_image_files(generated_root) if path not in before_images)
            if candidates:
                return max(candidates, key=self._safe_mtime)
            if time.time() >= deadline:
                return None
            time.sleep(0.2)

    def _copy_generated_image_to_exports(self, root_dir: Path, source_path: Path, *, run_id: str, node_id: str) -> Path:
        """Copy a generated artifact into the block output location.

        Args:
            root_dir: Directory path used by the block runtime.
            source_path: Filesystem path handled by the block.
            run_id: Identifier used to select a graph, port, output, or runtime object.
            node_id: Identifier used to select a graph, port, output, or runtime object.
        """
        extension = source_path.suffix.lower()
        if extension not in CODEX_GENERATED_IMAGE_EXTENSIONS:
            extension = ".png"
        target_path = self._next_image_export_path(root_dir, run_id=run_id, node_id=node_id, extension=extension)
        shutil.copy2(source_path, target_path)
        return target_path

    def _next_image_export_path(self, root_dir: Path, *, run_id: str, node_id: str, extension: str) -> Path:
        """Compute the next identifier or path used by this block.

        Args:
            root_dir: Directory path used by the block runtime.
            run_id: Identifier used to select a graph, port, output, or runtime object.
            node_id: Identifier used to select a graph, port, output, or runtime object.
            extension: Extension value used by this block helper.
        """
        target_dir = root_dir / "exports" / "images"
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_run_id = self._safe_file_stem(run_id) or "run"
        safe_node_id = self._safe_file_stem(node_id) or "image"
        normalized_extension = extension if extension.startswith(".") else f".{extension}"
        target_path = target_dir / f"{safe_run_id}_{safe_node_id}{normalized_extension}"
        index = 2
        while target_path.exists():
            target_path = target_dir / f"{safe_run_id}_{safe_node_id}_{index}{normalized_extension}"
            index += 1
        return target_path

    def _normalize_positive_float(self, value: Any, *, default: float) -> float:
        """Normalize a raw value into the format expected by the block.

        Args:
            value: Value to normalize, render, serialize, or process.
            default: Default value used when normalization fails.
        """
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _safe_file_stem(self, value: str) -> str:
        """Provide internal ImageBlock behavior for `_safe_file_stem`.

        Args:
            value: Value to normalize, render, serialize, or process.
        """
        return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "")).strip("_")

    def _safe_path_segment(self, value: str) -> str:
        """Provide internal ImageBlock behavior for `_safe_path_segment`.

        Args:
            value: Value to normalize, render, serialize, or process.
        """
        return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "")).strip("_")

    def _safe_mtime(self, path: Path) -> float:
        """Provide internal ImageBlock behavior for `_safe_mtime`.

        Args:
            path: Filesystem path handled by the block.
        """
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0
