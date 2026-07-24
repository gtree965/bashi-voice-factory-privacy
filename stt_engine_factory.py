from pathlib import Path

from engines.sherpa_parakeet import SherpaParakeetEngine
from engines.sherpa_sensevoice import SherpaSenseVoiceEngine
from stt_engine import SttEngine


STT_ENGINE_REGISTRY = {
    "sensevoice": SherpaSenseVoiceEngine,
    "parakeet": SherpaParakeetEngine,
}


def create_stt_engine(meta: dict, model_dir: Path) -> SttEngine:
    """Create an STT engine from its declared architecture or legacy name."""
    arch = (meta.get("arch") or "").lower()
    engine_class = STT_ENGINE_REGISTRY.get(arch)

    if engine_class is None:
        model_id = (meta.get("id") or "").lower()
        model_name = (meta.get("name") or "").lower()
        if "parakeet" in model_id or "parakeet" in model_name:
            engine_class = SherpaParakeetEngine
        elif any(
            key in model_id or key in model_name
            for key in ("sensevoice", "sense-voice")
        ):
            engine_class = SherpaSenseVoiceEngine

    if engine_class is None:
        raise RuntimeError(
            f"Unsupported STT model engine for {meta.get('id')}: "
            f"{meta.get('name', '')}"
        )

    return engine_class(model_dir)
