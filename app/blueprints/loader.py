import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from app.blueprints.base import BlueprintConfig
from app.config import settings

logger = logging.getLogger(__name__)

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

class BlueprintRegistry:
    _instance: Optional["BlueprintRegistry"] = None

    def __init__(self):
        self._blueprints: Dict[str, BlueprintConfig] = {}
        self._load_all()

    @classmethod
    def get_instance(cls) -> "BlueprintRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_all(self):
        if not SCHEMAS_DIR.exists():
            return

        for schema_file in SCHEMAS_DIR.glob("*.json"):
            try:
                data = json.loads(schema_file.read_text(encoding="utf-8"))
                bp = BlueprintConfig.model_validate(data)
                self._blueprints[bp.id] = bp
                logger.info(f"Loaded blueprint: {bp.id} ({bp.display_name})")
            except Exception as e:
                logger.error(f"Failed to load blueprint from {schema_file}: {e}")

    def get_blueprint(self, blueprint_id: str) -> Optional[BlueprintConfig]:
        return self._blueprints.get(blueprint_id)

    def get_active_blueprint(self) -> BlueprintConfig:
        active_id = getattr(settings, "ACTIVE_BLUEPRINT", "optical")
        bp = self.get_blueprint(active_id)
        if not bp:
            logger.warning(f"Active blueprint '{active_id}' not found, falling back to 'optical'")
            bp = self.get_blueprint("optical")
            if not bp:
                raise ValueError("No blueprints found in registry")
        return bp

    def list_blueprints(self) -> List[Dict[str, str]]:
        return [
            {
                "id": bp.id,
                "display_name": bp.display_name,
                "industry": bp.industry,
                "description": bp.description
            }
            for bp in self._blueprints.values()
        ]

def get_active_blueprint() -> BlueprintConfig:
    return BlueprintRegistry.get_instance().get_active_blueprint()

def get_blueprint(blueprint_id: str) -> Optional[BlueprintConfig]:
    return BlueprintRegistry.get_instance().get_blueprint(blueprint_id)

def list_available_blueprints() -> List[Dict[str, str]]:
    return BlueprintRegistry.get_instance().list_blueprints()
