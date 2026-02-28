# Getting Started: Generate Your First JP JSON

This guide walks you once through the full process of creating and exporting a Journey Profile JSON.
## 1. Start the Application

From the project root, run:

```bash
python3 Source/InfrastructureView.py
```

Alternatively start the JPGen.exe. 

The main window opens with three tabs:

1. `Infrastructure View`
2. `Parameter View`
3. `Settings`

## 2. Load Infrastructure Data

1. Open the `Parameter View` tab.
2. In the `Infrastructure` section, click `Browse…` and select an infrastructure JSON file.
3. Click `Load`.
4. Confirm that the status changes from `No infrastructure loaded.` to a loaded summary.

Tip: You can use `data_examples/ebd_v7_3_stations-infrastructure-description.json` for a first test run.

## 3. Build the Route in Infrastructure View

1. Switch to the `Infrastructure View` tab.
2. Make Timing Points visible:
   - Option A: Go to `Settings` and enable `Show all timing points`.
   - Option B: Left-click a track section to show Timing Points (TPs) on that section only.
3. Left-click a TP to set the start of the route.
4. Left-click additional TPs to extend the route step by step.

Useful controls while building:

1. Remove TP from route: `Shift + Right-click` on the TP.
2. Clear entire route: click `Clear route`.
3. Undo/Redo: `Ctrl + Z` / `Ctrl + Y`.

## 4. Set Timing Constraints on Selected TPs

1. Right-click a TP on your route.
2. In the timing dialog, set:
   - `Point type`: `STOP` or `PASS`
   - `Arrival time` (optional)
   - `Departure time` (optional)
3. Confirm with `OK`.
4. Repeat for each TP where timing or stop behavior is needed.

## 5. Set Journey Parameters

Go back to `Parameter View` and fill in:

1. `Train number`
2. `Train type`
3. `Driving strategy`
4. `Start time` (UTC format, e.g. `2026-02-28T12:00:00Z`)
5. `Dwell time (s)`

## 6. Export the Journey Profile JSON

1. Click `Generate Journey Profile`.
2. Choose file name and save location in the file dialog.
3. Confirm the success message (`Journey Profile generated: ...`).

You have now completed one full JP JSON generation workflow.

## 7. Quick Validation (Optional)

1. Open the exported JSON file.
2. Confirm it is not empty and contains route and timing-related content.
3. (Optional) In `Parameter View`, use `Load Journey Profile / Route` to load the file and verify that the route can be reconstructed.

## Troubleshooting

1. `No route`: You tried exporting before selecting route TPs.
2. `No infrastructure loaded`: Load infrastructure first in `Parameter View`.
3. `Generation failed`: Check that infrastructure, route, and parameters are set correctly, then retry.
