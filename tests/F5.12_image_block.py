#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Role: Verifies image block behavior.
# File Name: F5.12_image_block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2024-08-29
# -----------------------------------------------------------------------------

"""F5.12 - Bloc Image via Codex CLI simulé.

Le test injecte un faux `codex` qui émet `thread.started` et crée une image
dans `$CODEX_HOME/generated_images/<thread_id>/`. Le bloc `image` doit détecter
cette image, la copier dans `exports/images/` et émettre un chemin absolu.
"""

# Test cases:
# - FB1/FB2/FB3/FB4 - Run Image with a fake Codex CLI that emits thread.started and creates an image.
# - FB4 - Verify the image is copied into exports/images and the output is an absolute image path.
# - FB5 - Execute Image with an empty instruction and verify it fails clearly before invoking Codex.

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import os
import shutil
import tempfile

from ui_smoke_common import (
    create_run_api,
    data_edge,
    expect,
    graph_payload,
    isolated_server,
    text_node,
    wait_for_run_terminal,
)
from urllib.parse import quote
from block_test_packages import install_test_package, release_key, surface_payload

from blocs import get_block_definition
from bloxsmith_app.block_runtime import BlockRuntimeContext
from bloxsmith_app.block_ui import render_block_modal


@contextmanager
def fake_image_codex_cli():
    temp_dir = Path(tempfile.mkdtemp(prefix="bloxsmith-fake-image-codex-"))
    codex_home = temp_dir / "codex-home"
    codex_path = temp_dir / "codex"
    codex_path.write_text(
        """#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path
import sys

thread_id = "019f5000-0000-7000-8000-fakeimage0001"
args = sys.argv[1:]
output_path = ""
for index, arg in enumerate(args):
    if arg == "--output-last-message" and index + 1 < len(args):
        output_path = args[index + 1]
        break

codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
image_dir = codex_home / "generated_images" / thread_id
image_dir.mkdir(parents=True, exist_ok=True)
png_bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
(image_dir / "fake.png").write_bytes(png_bytes)

if output_path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(image_dir / "fake.png"), encoding="utf-8")

print(json.dumps({"type": "thread.started", "thread_id": thread_id}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0, "total_tokens": 2}}), flush=True)
""",
        encoding="utf-8",
    )
    codex_path.chmod(0o755)

    old_path = os.environ.get("PATH", "")
    old_codex_home = os.environ.get("CODEX_HOME")
    os.environ["PATH"] = f"{temp_dir}{os.pathsep}{old_path}"
    os.environ["CODEX_HOME"] = str(codex_home)
    try:
        yield codex_path
    finally:
        os.environ["PATH"] = old_path
        if old_codex_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_codex_home
        shutil.rmtree(temp_dir, ignore_errors=True)


def image_node() -> dict:
    return {
        "id": "image-1",
        "kind": "image",
        "title": "Image test",
        "position": {"x": 360, "y": 120},
        "inputs": [
            {"id": 1, "name": "instruction", "title": "Instruction", "accepts": ["message/*"], "multiplicity": "many"}
        ],
        "outputs": [
            {"id": 1, "name": "image", "title": "Image", "emits": ["image/path", "file/path"], "multiplicity": "many"}
        ],
        "config": {
            "image_model": "gpt-5.5",
            "image_effort": "low",
            "image_sandbox": "workspace-write",
            "image_timeout_sec": 10,
        },
    }


def _verify_empty_instruction_failure() -> None:
    result = get_block_definition("image").execute_runtime(
        BlockRuntimeContext(
            run_id="unit-run",
            node_id="image-empty",
            kind="image",
            title="Image empty",
            config={},
            inputs={},
            input_content_types={},
            input_message="",
            input_ports=(SimpleNamespace(id=1, name="instruction"),),
            output_ports=(SimpleNamespace(id=1, name="image"),),
            root_dir=Path.cwd(),
        )
    )
    expect(result.status == "failed", "Image sans instruction doit échouer.")
    expect("instruction" in result.error, "L'erreur Image vide doit mentionner l'instruction.")


def _verify_image_ui_contract() -> None:
    """TC6 - Image modal is block-owned and protected from runtime polling replacement."""

    modal = render_block_modal("image", {"node": image_node(), "runtime": {}})
    html = str(modal.get("html") or "")
    assets = modal.get("assets") or []
    js = (Path(__file__).resolve().parents[1] / "assets/js/block_modal.js").read_text(encoding="utf-8")
    expect('data-node-kind="image"' in html, "Le modal Image doit venir du bloc.")
    expect('data-block-runtime-refresh="autonomous"' in html, "Le modal Image doit gerer son refresh runtime.")
    expect("export function mount" in js, "Le JS Image doit monter le modal via le registre block UI.")


def main() -> None:
    _verify_empty_instruction_failure()
    _verify_image_ui_contract()
    with fake_image_codex_cli():
        with isolated_server() as server:
            # Les surfaces sont des assets de release : le bundled kind n'en sert aucun.
            model = install_test_package(server, "image")
            key = quote(release_key(model), safe="")
            served = lambda payload, suffix: next(
                asset["path"] for asset in payload["assets"] if asset["path"].endswith(suffix))
            document = graph_payload(
                "F5 Image",
                [
                    text_node("text-1", "Instruction image", "un chat réaliste", 80, 120),
                    image_node(),
                ],
                [data_edge("edge-text-image", "text-1", 1, "image-1", 1)],
            )
            created = create_run_api(server, document, runtime_mode="centralized")
            run = wait_for_run_terminal(server, str(created.get("run_id") or ""), timeout_sec=20)

            expect(run.get("status") == "success", "Le run image doit réussir avec le faux Codex.")
            output = run.get("output_values", {}).get("image-1:1", {})
            image_path = Path(str(output.get("value") or ""))
            expect(image_path.is_absolute(), "Le bloc image doit émettre un chemin absolu.")
            expect(image_path.is_file(), "L'image copiée est absente.")
            expect(server.root_dir.resolve() in image_path.resolve().parents, "L'image doit être copiée dans le projet de test.")
            expect("exports/images" in str(image_path), "L'image doit être copiée dans exports/images/.")
            expect(output.get("content_type") == "image/path", "Le content_type image doit être image/path.")
    print("[ok] F5.12_image_block")


if __name__ == "__main__":
    main()
