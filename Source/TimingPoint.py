from uuid import UUID
from typing import Optional, Union
from Track import Track

class TimingPoint:
    trackId: UUID                 # alternatively str
    tracK: Track
    id: int
    targetNodeId: UUID
    distanceToTargetNodeInMeters: float
    stoppingLocationId: Optional[str]
    segmentProfileId: int

    def __init__(
        self,
        trackId: Union[str, UUID],
        track: Track,
        id: int,
        targetNodeId: Union[str, UUID],
        distanceToTargetNodeInMeters: float,
        stoppingLocationId: Optional[str],
        segmentProfileId: int,
    ):
        self.trackId = trackId if isinstance(trackId, UUID) else UUID(trackId)
        self.track = track
        self.id = int(id)
        self.targetNodeId = targetNodeId if isinstance(targetNodeId, UUID) else UUID(targetNodeId)
        self.distanceToTargetNodeInMeters = float(distanceToTargetNodeInMeters)
        self.stoppingLocationId = stoppingLocationId
        self.segmentProfileId = int(segmentProfileId)

