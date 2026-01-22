from __future__ import annotations
import numpy as np
from dataclasses import dataclass
import documents.driving_dynamic.acceleration_deceleration_data as acc

# Unified dictionary for train acceleration and deceleration data
train_data = {
    "S1": {
        "accel": np.array(acc.acceleration_steps_s1),
        "decel": np.array(acc.deceleration_steps_s1)
    },
    "S2": {
        "accel": np.array(acc.acceleration_steps_s2),
        "decel": np.array(acc.deceleration_steps_s2)
    },
    "IC100": {
        "accel": np.array(acc.acceleration_steps_ic100),
        "decel": np.array(acc.deceleration_steps_ic100)
    },
    "RB20": {
        "accel": np.array(acc.acceleration_steps_rb20),
        "decel": np.array(acc.deceleration_steps_rb20)
    },
    "RB40": {
        "accel": np.array(acc.acceleration_steps_rb40),
        "decel": np.array(acc.deceleration_steps_rb40)
    },
    "RE50": {
        "accel": np.array(acc.acceleration_steps_re50),
        "decel": np.array(acc.deceleration_steps_re50)
    }
}

@dataclass
class TrainState:
    velocity: float = 0.0
    elapsed_time: float = 0.0
    total_distance: float = 0.0
    # State tracking for acceleration/deceleration curves
    # We use index in the velocity_steps array
    accel_idx: int = 0
    decel_idx: int = 0

def simulate_travel(
    train_type: str, 
    distance: float, 
    state: TrainState, 
    mode: str = "accel", 
    speed_restriction: float = np.inf, 
    time_step: float = 0.1
) -> float:
    """
    Simulates travel over a given distance and updates the state.
    Returns the time taken for this segment.
    """
    if distance <= 0:
        return 0.0
    
    data = train_data.get(train_type, train_data["S1"])
    v_steps = data["accel"] if mode == "accel" else data["decel"]
    
    target_dist = state.total_distance + distance
    segment_time = 0.0
    
    while state.total_distance < target_dist:
        # Get current velocity from steps
        idx = state.accel_idx if mode == "accel" else state.decel_idx
        v_idx = min(idx, len(v_steps) - 1)
        
        cur_v = v_steps[v_idx]
        
        # Apply speed restriction
        effective_v = min(cur_v, speed_restriction)
        if effective_v <= 0 and mode == "accel" and state.total_distance < target_dist:
            effective_v = 0.1 # Kickstart
            
        # Move
        dist_move = effective_v * time_step
        
        # Check if we overshoot
        if state.total_distance + dist_move >= target_dist:
            remaining = target_dist - state.total_distance
            move_time = remaining / effective_v if effective_v > 0 else 0
            segment_time += move_time
            state.total_distance = target_dist
            state.velocity = effective_v
            state.elapsed_time += move_time
            break
            
        state.total_distance += dist_move
        state.velocity = effective_v
        state.elapsed_time += time_step
        segment_time += time_step
        
        if mode == "accel":
            state.accel_idx += 1
        else:
            state.decel_idx += 1
            
        # Handle end of data
        if idx >= len(v_steps) - 1:
            remaining = target_dist - state.total_distance
            move_time = remaining / effective_v if effective_v > 0 else 0
            segment_time += move_time
            state.total_distance = target_dist
            state.elapsed_time += move_time
            break
            
    return segment_time

# Backward compatibility wrappers
def travel_time_for_distance(train: str, distance: float, speed_restriction: float = np.inf, time_diff: float = 0.1) -> float:
    state = TrainState()
    return simulate_travel(train, distance, state, mode="accel", speed_restriction=speed_restriction, time_step=time_diff)

def time_till_end_node(train: str, distance: float, speed_restriction: float = np.inf, time_diff: float = 0.1) -> float:
    return travel_time_for_distance(train, distance, speed_restriction, time_diff)
