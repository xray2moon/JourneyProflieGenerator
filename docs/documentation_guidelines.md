# Documentation Guidelines

This document outlines the structure and rules for the documentation in the `JourneyProflieGenerator/docs` directory.

## Directory Structure

The documentation is divided into two main areas:

*   **`code_documentation/`**: Contains technical documentation for developers.
*   **`user_documentation/`**: Contains guides and manuals for end-users.

## Code Documentation Guidelines

These guidelines apply to the documentation of individual components within the `code_documentation` directory (excluding `architecture_overview.md`, which has separate instructions). This includes files like `models.md`, `controllers.md`, `services.md`, and `views.md`.

### Structure for Component Documentation

When documenting a component (e.g., a specific model or controller), follow this structure:

1.  **Overview/Description:** Provide a short, high-level description of the component's overall purpose and how it works.
2.  **Core Functions:** Explain the functionality and logic of the most important, complex, or business-critical functions/methods within the component. These functions must be documented both inline within the code (using appropriate docstrings/comments) and detailed in these external markdown files.
3.  **Minor Functions (< 30 lines):** Do not document these extensively in the external markdown files. Rely on clear naming conventions and inline code comments to explain their purpose.

## Architecture Overview

The `architecture_overview.md` file provides a high-level view of the system's design and how components interact. (Detailed instructions for this file will be added separately).
