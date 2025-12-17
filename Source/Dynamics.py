from email.policy import default
from uuid import UUID
import numpy as np
import documents.driving_dynamic.acceleration_deceleration_data as acc
from TimingPoint import TimingPoint
from Track import Track

train_dict = {"S1":np.array(acc.acceleration_steps_s1),
              "S2":np.array(acc.acceleration_steps_s2),
              "IC100":np.array(acc.acceleration_steps_ic100),
              "RB20":np.array(acc.acceleration_steps_rb20),
              "RB40":np.array(acc.acceleration_steps_rb40),
              "RE50":np.array(acc.acceleration_steps_re50)}

default_tracks: list[Track] = []


# Calculating the required time to travel from a timing point to its target node
def time_till_end_node(train: str, distance: float, speed_restriction: float = np.inf, time_diff: float = 0.1) -> float:
    cur_dist = 0
    velocity_data = train_dict[train]
    idx = 0
    time = 0

    while cur_dist < distance:
        cur_velocity = min(velocity_data[idx], speed_restriction)
        next_dist = cur_dist + time_diff * cur_velocity
        if next_dist >= distance:
            time += (distance - cur_dist) / cur_velocity
            break
        cur_dist = next_dist
        idx += 1
        time += time_diff

    return time


# TP has distanceToTargetNodeInMeters and trackId, Track has lengthMeter
# train_track is the track of the train (train at beginning of track)
# Assuming one track's source node is another track's target node and sourceNodes are unique
def distance_to_timing_point(train_track: Track, tp: TimingPoint):
    tp_track = tp.track
    total_length: int = 0
    while not tp_track.id == train_track.id:
        total_length += tp_track.lengthMeter
        train_track = find_by_source_node_id(train_track.targetNodeId)
    total_length += tp_track.lengthMeter - tp.distanceToTargetNodeInMeters
    return total_length


def find_by_source_node_id(source_id: UUID, tracks: list[Track] = default_tracks):
    result = None
    for potential_track in tracks:
        if potential_track.sourceNodeId == source_id:
            result = potential_track
    return result