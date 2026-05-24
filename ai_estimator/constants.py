from __future__ import annotations

from dataclasses import dataclass


TRADE_NAMES = [
    "general",
    "architectural",
    "structural",
    "civil_site",
    "landscape",
    "interiors_finishes",
    "fire_protection",
    "plumbing",
    "mechanical_hvac",
    "electrical",
    "low_voltage_communications_it",
    "security_access_alarm",
    "conveying",
    "equipment_specialties",
    "other",
]


DISCIPLINE_PREFIX_TO_TRADE: dict[str, str] = {
    "G": "general",
    "A": "architectural",
    "S": "structural",
    "C": "civil_site",
    "L": "landscape",
    "I": "interiors_finishes",
    "F": "fire_protection",
    "FP": "fire_protection",
    "P": "plumbing",
    "M": "mechanical_hvac",
    "E": "electrical",
    "T": "low_voltage_communications_it",
    "FA": "security_access_alarm",
    "Q": "equipment_specialties",
    "X": "other",
    "R": "other",
    "O": "other",
    "Z": "other",
}


TRADE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "general": ("code", "cover sheet", "index", "notes", "legend", "life safety"),
    "architectural": ("architectural", "floor plan", "door schedule", "window schedule", "room finish"),
    "structural": ("structural", "foundation", "beam", "column", "rebar", "slab"),
    "civil_site": ("civil", "grading", "site plan", "utility", "drainage", "earthwork"),
    "landscape": ("landscape", "planting", "irrigation", "hardscape"),
    "interiors_finishes": ("interior", "finish", "millwork", "ceiling", "partition"),
    "fire_protection": ("sprinkler", "standpipe", "fire suppression", "fire protection"),
    "plumbing": ("plumbing", "domestic water", "sanitary", "storm", "fixture"),
    "mechanical_hvac": ("hvac", "mechanical", "duct", "air handling", "rtu", "chiller"),
    "electrical": ("electrical", "power", "lighting", "panelboard", "one-line"),
    "low_voltage_communications_it": ("telecom", "data", "communications", "fiber", "it room"),
    "security_access_alarm": ("security", "access control", "intrusion", "fire alarm", "cctv"),
    "conveying": ("elevator", "escalator", "lift", "conveying"),
    "equipment_specialties": ("equipment", "specialty", "kitchen equipment", "lab equipment"),
}


SHEET_TYPE_MAP: dict[str, str] = {
    "0": "other",
    "1": "plan",
    "2": "elevation",
    "3": "section",
    "4": "detail",
    "5": "schedule",
    "6": "schedule",
    "7": "other",
    "8": "other",
    "9": "other",
}


DEFAULT_CSI_BY_TRADE: dict[str, list[str]] = {
    "architectural": ["06", "07", "08", "09", "10"],
    "structural": ["03", "04", "05"],
    "civil_site": ["31", "32", "33"],
    "landscape": ["32"],
    "interiors_finishes": ["09", "12"],
    "fire_protection": ["21"],
    "plumbing": ["22"],
    "mechanical_hvac": ["23"],
    "electrical": ["26"],
    "low_voltage_communications_it": ["27"],
    "security_access_alarm": ["28"],
    "conveying": ["14"],
    "equipment_specialties": ["11"],
}


@dataclass(frozen=True)
class TradeScope:
    requested_mode: str
    requested_trades: list[str]
    detected_trades: list[str]
    analyzed_trades: list[str]
    skipped_trades: list[dict[str, str]]
    sheet_trade_map: list[dict[str, object]]

