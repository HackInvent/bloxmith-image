#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Role: Verifies active image block behavior.
# File Name: F11.13_active_image_block.py
# Author: Alexandre EL
# Email: alex@hackinvent.com
# Created Date: 2024-07-23
# -----------------------------------------------------------------------------

"""F11.13 - Bloc Image en runtime ZeroMQ actif.

Le test injecte un faux `codex` générant une image dans `$CODEX_HOME`, puis
vérifie que le runner `image` actif détecte l'image, la copie dans
`exports/images/` et publie son chemin absolu sans fallback centralisé.
"""

# Test cases:
# - FB1/FB2/FB3/FB4 - Run Image in active runtime with a fake Codex CLI that creates an image asset.
# - FB4 - Verify the active worker copies the generated image and publishes its path.

from contextlib import contextmanager
from pathlib import Path
import base64
import os
import shutil
import tempfile
import time

from ui_smoke_common import (
    create_run_api,
    data_edge,
    expect,
    graph_payload,
    isolated_server,
    play_run_api,
    prepare_run_api,
    stop_run_api,
    text_node,
    wait_for_run_predicate,
    wait_for_run_terminal,
)


@contextmanager
def fake_image_codex_cli():
    temp_dir = Path(tempfile.mkdtemp(prefix="bloxsmith-fake-active-image-"))
    codex_home = temp_dir / "codex-home"
    codex_path = temp_dir / "codex"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    codex_path.write_text(
        f"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

thread_id = "019f8000-0000-7000-8000-activeimage01"
args = sys.argv[1:]
output_path = ""
for index, arg in enumerate(args):
    if arg == "--output-last-message" and index + 1 < len(args):
        output_path = args[index + 1]
        break

codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
image_dir = codex_home / "generated_images" / thread_id
image_dir.mkdir(parents=True, exist_ok=True)
image_path = image_dir / "fake.png"
image_path.write_bytes({png_bytes!r})

if output_path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(image_path), encoding="utf-8")

print(json.dumps({{"type": "thread.started", "thread_id": thread_id}}), flush=True)
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "reasoning_output_tokens": 0, "total_tokens": 2}}}}), flush=True)
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
        "title": "Image active",
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


def main() -> None:
    with fake_image_codex_cli():
        with isolated_server() as server:
            document = graph_payload(
                "F11 active image",
                [
                    text_node("text-1", "Instruction image", "a realistic cat", 80, 120),
                    image_node(),
                ],
                [data_edge("edge-text-image", "text-1", 1, "image-1", 1)],
            )
            created = create_run_api(server, document, runtime_mode="zeromq_active")
            run = wait_for_run_terminal(server, str(created.get("run_id") or ""), timeout_sec=25)
            logs = "\n".join(run.get("logs", []))

            expect(run.get("status") == "success", "The active image run must succeed.")
            expect("fallback centralized" not in logs, "The active image block must not fall back to the centralized engine.")
            output = run.get("output_values", {}).get("image-1:1", {})
            image_path = Path(str(output.get("value") or ""))
            expect(image_path.is_absolute(), "Le bloc image actif doit émettre un chemin absolu.")
            expect(image_path.is_file(), "The copied active image is missing.")
            expect("exports/images" in str(image_path), "L'image active doit être copiée dans exports/images/.")
            expect(run.get("results", {}).get("image-1", {}).get("transport") == "zeromq_active", "Image must run through zeromq_active.")

            prepared = prepare_run_api(server, document, runtime_mode="zeromq_active")
            active_run_id = str(prepared.get("run_id") or "")
            time.sleep(1.0)
            play_run_api(server, active_run_id)
            active_state = wait_for_run_predicate(
                server,
                active_run_id,
                lambda state: bool(state.get("output_values", {}).get("image-1:1", {}).get("value")),
                "The active image block did not publish an image on Load/Play.",
                timeout_sec=25,
            )
            active_image_path = Path(str(active_state.get("output_values", {}).get("image-1:1", {}).get("value") or ""))
            expect(active_state.get("status") == "running", "The active image runtime must stay alive after Play.")
            expect(active_image_path.is_file(), "The copied active Load/Play image is missing.")
            stop_run_api(server, active_run_id)
            stopped = wait_for_run_terminal(server, active_run_id, timeout_sec=10)
            expect(stopped.get("status") == "cancelled", "Stop must end the active image runtime.")
    print("[ok] F11.13_active_image_block")


if __name__ == "__main__":
    main()
