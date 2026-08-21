from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class FieldOption(BaseModel):
    name: str
    color: str = "default"

class BlueprintField(BaseModel):
    name: str  # JSON key name (e.g. "od_sph", "tooth_numbers", "vehicle_model")
    label: str  # Human readable label for Notion / PDF / UI
    type: str  # "text", "number", "select", "date"
    notion_type: str = "rich_text"  # "title", "rich_text", "number", "select", "date"
    options: Optional[List[FieldOption]] = None  # For select types
    description: str = ""  # Guide for the LLM extraction prompt
    in_pdf_table: bool = False
    in_pdf_header: bool = False

class GatingRule(BaseModel):
    min_confidence: float = 0.85
    max_auto_approve_value: float = 3000.0
    gated_categories: List[str] = []  # e.g. ["progressive", "bifocal", "implant", "engine_overhaul"]
    gated_category_field: Optional[str] = None  # e.g. "lens_type", "restoration_type", "service_type"

class BlueprintConfig(BaseModel):
    id: str
    display_name: str
    industry: str
    description: str
    currency: str = "INR"
    currency_symbol: str = "₹"
    system_instruction_addendum: str = ""
    few_shot_examples: List[Dict[str, Any]] = []
    fields: List[BlueprintField] = []
    gating_rules: GatingRule = Field(default_factory=GatingRule)
    pdf_title: str = "JOB DISPATCH SLIP"
    pdf_table_columns: List[str] = []
