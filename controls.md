# Journey Profile Generator

## About the Program

The Journey Profile Generator is a tool for interactively planning train journeys using digital rail infrastructure data. The planned journey can then be exported as a JSON file.

A journey profile includes the following aspects:

- Exact path: Which tracks and switches are traversed, and in what order.
- Time constraints: When the train is scheduled to arrive at or depart from specific points.
- Technical parameters: Which train type is used and which driving strategy is applied.

The output is a standardized JSON file that can be used for different purposes.

## Controls

- `Show all timing points`: In the settings, enable the option to show all Timing Points (TPs).
- `Show section timing points`: Left-click a section (between two switches) to show all TPs on that section.
- `Add TP to route`: Left-click a timing point. The system then automatically calculates the shortest path to the next point.
- `Remove TP from route`: Press `Shift` and right-click a timing point.
- `Edit TP properties`: Right-click the selected timing point to set arrival/departure times and mark the point as pass or stop.
- `Clear route`: Click `Clear route` in the top-left corner of the screen to restart planning.
- `Undo/Redo`: Use `Ctrl + Z` to undo and `Ctrl + Y` to redo.

## Parameters

- Train-specific parameters and train type can be configured in the Parameter view.
- Driving style can also be set in the Parameter view.
- To import an infrastructure file, use the browse/load icons in the Parameter view.
- To modify an existing journey profile, load the Journey Profile JSON file in the `Load Journey` section of the Parameter view.
- To export the planned route, click `Generate Journey Profile` in the Parameter view.
