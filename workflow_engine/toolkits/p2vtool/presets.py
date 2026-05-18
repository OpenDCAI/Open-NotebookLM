"""Built-in paper2video avatars and CosyVoice preset metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

P2V_ROOT = Path(__file__).resolve().parent
AVATAR_DIR = P2V_ROOT / "avatar"
COSYVOICE_PRESET_DIR = P2V_ROOT / "cosyvoice" / "v3-flash"
DEFAULT_TTS_MODEL = "cosyvoice-v3-flash"

AVATAR_LABELS: Dict[str, str] = {
    "avatar1": "系统数字人 1",
    "avatar2": "系统数字人 2",
}

VOICE_LABELS: Dict[str, str] = {
    "longanyang": "龙安洋",
    "longanhuan": "龙安欢",
    "longanwen": "龙安温",
    "longanwen_v3": "龙安温",
    "longanzhi": "龙安智",
    "longanzhi_v3": "龙安智",
}

COSYVOICE_VOICE_LIST_URL = (
    "https://help.aliyun.com/zh/model-studio/developer-reference/cosyvoice-voice-list"
)


def voice_id_from_filename(name: str) -> str:
    stem = Path(name).stem
    if stem.endswith("_v3"):
        return stem[:-3]
    return stem


def list_system_avatars() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not AVATAR_DIR.is_dir():
        return items
    for path in sorted(AVATAR_DIR.glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        avatar_id = path.stem
        items.append(
            {
                "id": avatar_id,
                "label": AVATAR_LABELS.get(avatar_id, avatar_id),
                "filename": path.name,
                "path": str(path.resolve()),
            }
        )
    return items


def list_cosyvoice_presets() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not COSYVOICE_PRESET_DIR.is_dir():
        return items
    for path in sorted(COSYVOICE_PRESET_DIR.glob("*.wav")):
        voice_id = voice_id_from_filename(path.name)
        items.append(
            {
                "id": voice_id,
                "label": VOICE_LABELS.get(path.stem, VOICE_LABELS.get(voice_id, voice_id)),
                "filename": path.name,
                "preview_path": str(path.resolve()),
                "tts_model": DEFAULT_TTS_MODEL,
            }
        )
    return items


def resolve_system_avatar_path(avatar_id: str) -> str:
    raw = (avatar_id or "").strip()
    if not raw:
        raise ValueError("avatar_id 不能为空")
    candidate = AVATAR_DIR / raw
    if candidate.suffix:
        path = candidate
    else:
        path = AVATAR_DIR / f"{raw}.png"
    if not path.is_file():
        raise FileNotFoundError(f"系统数字人不存在: {raw}")
    return str(path.resolve())


def resolve_preset_asset_path(*, kind: str, asset_id: str) -> Path:
    kind = (kind or "").strip().lower()
    asset_id = (asset_id or "").strip()
    if not asset_id or ".." in asset_id or "/" in asset_id or "\\" in asset_id:
        raise ValueError("非法资源 id")
    if kind == "avatar":
        return Path(resolve_system_avatar_path(asset_id))
    if kind == "voice":
        path = COSYVOICE_PRESET_DIR / asset_id
        if not path.is_file():
            path = COSYVOICE_PRESET_DIR / f"{asset_id}.wav"
        if not path.is_file():
            for candidate in COSYVOICE_PRESET_DIR.glob("*.wav"):
                if voice_id_from_filename(candidate.name) == asset_id:
                    return candidate
            raise FileNotFoundError(f"音色预览不存在: {asset_id}")
        return path.resolve()
    raise ValueError(f"不支持的资源类型: {kind}")
