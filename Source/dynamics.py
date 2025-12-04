import numpy as np
import documents.driving_dynamic.acceleration_deceleration_data as acc

train_dict = {"S1":np.array(acc.acceleration_steps_s1),
              "S2":np.array(acc.acceleration_steps_s2),
              "IC100":np.array(acc.acceleration_steps_ic100),
              "RB20":np.array(acc.acceleration_steps_rb20),
              "RB40":np.array(acc.acceleration_steps_rb40),
              "RE50":np.array(acc.acceleration_steps_re50)}

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