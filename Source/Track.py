from dataclasses import dataclass
from uuid import UUID
from typing import Any

@dataclass(frozen=True, slots=True)
class ShapingPoint:
    x: float
    y: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShapingPoint":
        return cls(x=float(d["x"]), y=float(d["y"]))


@dataclass(frozen=True, slots=True)
class Track:
    id: UUID
    sourceNodeId: UUID
    targetNodeId: UUID
    shapingPoints: list[ShapingPoint]
    lengthMeter: float
    numericId: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Track":
        return cls(
            id=UUID(d["id"]),
            sourceNodeId=UUID(d["sourceNodeId"]),
            targetNodeId=UUID(d["targetNodeId"]),
            shapingPoints=[ShapingPoint.from_dict(p) for p in d.get("shapingPoints", [])],
            lengthMeter=float(d["lengthMeter"]),
            numericId=int(d["numericId"]),
        )
