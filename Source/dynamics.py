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
    braking_triggered: bool = False

def get_braking_distance(train_type: str, velocity: float) -> float:
    """
    Calculates the distance required to stop from a given velocity.
    Uses the deceleration curve backwards.
    """
    if velocity <= 0:
        return 0.0
    data = train_data.get(train_type, train_data["S1"])
    v_steps = data["decel"]
    
    # Find the index where v_steps is closest to velocity
    idx = np.searchsorted(v_steps, velocity)
    if idx >= len(v_steps):
        idx = len(v_steps) - 1
        
    # Braking distance is the sum of speeds in the curve from idx down to 0, times time_step (0.1s)
    dist = np.sum(v_steps[:idx+1]) * 0.1
    return dist

def simulate_travel(
    train_type: str, 
    distance: float, 
    state: TrainState, 
    mode: str = "accel", 
    speed_restriction: float = np.inf, 
    time_step: float = 0.1,
    distance_to_stop: float = np.inf
) -> float:
    """
    Simulates travel over a given distance and updates the state.
    Returns the time taken for this segment.
    If distance_to_stop is provided, it will transition to deceleration 
    automatically when needed.
    """
    if distance <= 0:
        # If we are at a stop point, reset braking flag for next journey leg
        if distance_to_stop <= 0.1:
            state.braking_triggered = False
            state.accel_idx = 0
            state.decel_idx = 0
            state.velocity = 0.0
        return 0.0
    
    data = train_data.get(train_type, train_data["S1"])
    accel_v = data["accel"]
    decel_v = data["decel"]
    
    target_dist = state.total_distance + distance
    start_dist = state.total_distance
    segment_time = 0.0
    
    while state.total_distance < target_dist:
        # 1. Decide mode: should we brake?
        current_mode = mode
        dist_traveled_this_call = state.total_distance - start_dist
        if distance_to_stop < np.inf and not state.braking_triggered:
            remaining_to_stop = distance_to_stop - dist_traveled_this_call
            
            # Safety margin of 2 meters
            if remaining_to_stop <= get_braking_distance(train_type, state.velocity) + 2.0:
                state.braking_triggered = True
        
        if state.braking_triggered:
            current_mode = "decel"
        
        # 2. Get current velocity step
        if current_mode == "accel":
            v_steps = accel_v
            v_idx = min(state.accel_idx, len(v_steps) - 1)
            cur_v = v_steps[v_idx]
            state.decel_idx = np.searchsorted(decel_v, cur_v)
        else:
            v_steps = decel_v
            v_idx = max(0, state.decel_idx)
            cur_v = v_steps[v_idx]
            state.accel_idx = np.searchsorted(accel_v, cur_v)

        # 3. Apply speed restriction
        effective_v = min(cur_v, speed_restriction)
        if effective_v <= 0 and current_mode == "accel" and state.total_distance < target_dist:
            effective_v = 0.1 # Kickstart
            
        # 4. Move
        dist_move = effective_v * time_step
        
        # 5. Check if we overshoot target_dist
        if state.total_distance + dist_move >= target_dist:
            remaining = target_dist - state.total_distance
            
            # If we are in decel mode and heading to a stop AT this distance, force zero velocity
            if state.braking_triggered and abs(distance_to_stop - dist_traveled_this_call - remaining) < 0.1:
                state.velocity = 0.0
                state.total_distance = target_dist
                # Move time is based on average of current velocity and zero
                move_time = remaining / (effective_v / 2.0) if effective_v > 0.1 else 0
                state.elapsed_time += move_time
                segment_time += move_time
            else:
                move_time = remaining / effective_v if effective_v > 0 else 0
                state.velocity = effective_v
                state.total_distance = target_dist
                state.elapsed_time += move_time
                segment_time += move_time
            break
            
        state.total_distance += dist_move
        state.velocity = effective_v
        state.elapsed_time += time_step
        segment_time += time_step
        
        if current_mode == "accel":
            state.accel_idx += 1
        else:
            state.decel_idx = max(0, state.decel_idx - 1)
            
        # 6. Handle end of data or speed zero
        if (current_mode == "accel" and state.accel_idx >= len(accel_v)) or \
           (current_mode == "decel" and (state.decel_idx <= 0 or state.velocity < 0.01)):
            remaining = target_dist - state.total_distance
            # If we are decelerating and reached almost zero speed, 
            # we should be at the stop. Snap to target.
            state.total_distance = target_dist
            state.velocity = 0.0
            # If we were crawling, assume a minimal speed for remaining time to avoid 0-time jumps
            move_time = remaining / effective_v if effective_v > 0.1 else remaining / 1.0
            state.elapsed_time += move_time
            segment_time += move_time
            break
            
    return segment_time

# Backward compatibility wrappers
def travel_time_for_distance(train: str, distance: float, speed_restriction: float = np.inf, time_diff: float = 0.1) -> float:
    state = TrainState()
    return simulate_travel(train, distance, state, mode="accel", speed_restriction=speed_restriction, time_step=time_diff)

def time_till_end_node(train: str, distance: float, speed_restriction: float = np.inf, time_diff: float = 0.1) -> float:
    return travel_time_for_distance(train, distance, speed_restriction, time_diff)
