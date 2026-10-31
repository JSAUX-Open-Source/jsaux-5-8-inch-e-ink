from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


def _load_main_module():
    plugin_dir = Path(__file__).resolve().parent
    fake_decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(plugin_dir),
        logger=types.SimpleNamespace(
            info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        emit=lambda *a, **k: None,
    )
    sys.modules["decky"] = fake_decky
    spec = importlib.util.spec_from_file_location("jsaux_render_main", plugin_dir / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: render_subprocess.py <payload.json>", file=sys.stderr)
        return 2

    payload_path = Path(sys.argv[1])
    request = json.loads(payload_path.read_text(encoding="utf-8"))
    module = _load_main_module()
    module._ensure_pillow()
    data = module._render_bytes_locally(request["mode"], request["payload"])
    sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
