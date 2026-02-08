# Detailed Testing Plan for Journey Profile Generator

## 1. Objective
Ensure the `JourneyProfileGenerator` accurately simulates train physics, respects infrastructure constraints, and produces valid Journey Profile JSON output consistent with the provided data examples.

## 2. Scope
- **Unit Testing**: Physics simulation logic (`Source/dynamics.py`).
- **Integration Testing**: Journey Profile export logic (`Source/journey_profile_exporter.py`).
- **Data Validation**: Compliance with `acceleration_deceleration_data.py`.
- **Constraint Verification**: "Natural" constraints (e.g., stopping at 0 velocity, strictly increasing timestamps).

## 3. Test Suites

### Suite A: Dynamics Core Verification (Physics Engine)
**Goal**: Verify `simulate_travel` exactly reproduces the reference velocity curves.

*   **Test A.1: Acceleration Consistency**
    *   **Input**: Train "S1", Mode "accel", infinite distance.
    *   **Verification**: At each time step `t` (0.1s intervals), the simulated velocity must match `acceleration_steps_s1[t]` within floating-point tolerance.
    *   **Rationale**: Ensures the simulation steps through the lookup table correctly.

*   **Test A.2: Deceleration Consistency**
    *   **Input**: Train "S1", Initial Velocity = Max Velocity, Mode "decel".
    *   **Verification**: Velocity must decrease according to `deceleration_steps_s1`.
    *   **Rationale**: Ensures braking curves are applied correctly.

*   **Test A.3: Precision Stopping (Natural Constraint)**
    *   **Input**: Train traveling at velocity `v`. Distance to stop `d` = exact braking distance for `v`.
    *   **Verification**: Final velocity is exactly `0.0`. Distance traveled is exactly `d`.
    *   **Rationale**: The train must stop exactly where required, not overshoot or undershoot.

*   **Test A.4: Look-ahead Braking**
    *   **Input**: Train accelerating towards a stop at distance `D`.
    *   **Verification**: Simulation correctly identifies the "point of no return" and switches from acceleration to deceleration automatically to stop at `D`.

### Suite B: Journey Profile Exporter Verification
**Goal**: Verify the end-to-end generation of the JSON profile.

*   **Test B.1: Profile Structure & Schema**
    *   **Input**: Mocked infrastructure (Route A -> B -> C).
    *   **Verification**: Generated JSON has correct keys (`meta`, `segmentProfileReferences`, `timingPointConstraints`).
    *   **Constraint**: Check against schema of `data_examples/story3-initial-journeyprofile1.json`.

*   **Test B.2: Timing Consistency (Natural Constraint)**
    *   **Input**: Route with multiple Timing Points (TPs).
    *   **Verification**: `arrivalTimestamp` at TP `n` < `arrivalTimestamp` at TP `n+1`.
    *   **Verification**: If TP is a STOP, `departureTimestamp` = `arrivalTimestamp` + `dwellTime`.

*   **Test B.3: Velocity Reset at Stops**
    *   **Input**: Route with an intermediate STOP.
    *   **Verification**: Train state (velocity) resets to 0.0 at the stop. The segment following the stop starts with acceleration from 0.

### Suite C: Edge Cases & Stress Tests

*   **C.1: Zero Length Segments**
    *   **Scenario**: Two TPs at the same location (distance 0).
    *   **Expected**: Simulation handles delta 0 gracefully (0 time passed).

*   **C.2: Insufficient Braking Distance**
    *   **Scenario**: Distance to next stop is less than required braking distance for current speed.
    *   **Expected**: Simulation should clamp to valid physics (emergency stop or theoretical best effort), ensuring velocity eventually hits 0, possibly overshooting (or reporting error).

*   **C.3: Maximum Speed Limits**
    *   **Scenario**: Track has a speed restriction lower than train max speed.
    *   **Expected**: Velocity caps at the restriction.

*   **C.4: Reversals**
    *   **Scenario**: Route involves a direction reversal.
    *   **Expected**: Train stops, dwells, and state resets. `direction` field in JSON flips.

## 4. Verification Script (`testing/verify_dynamics.py`)
A standalone script will be created to execute **Suite A** immediately.

## 5. Further Areas for Testing
*   **Segment Profile ID Changes**: Verify new segments are created when `segment_profile_id` changes between TPs.
*   **Floating Point Drift**: Simulate long journeys (100km+) to ensure 0.1s time steps don't accumulate significant distance error.
*   **Different Train Types**: Repeat Suite A for "S2", "IC100", "RB20", etc., to ensure data dictionary keys are correct.
