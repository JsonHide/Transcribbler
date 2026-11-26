# Desktop App as Primary Experience with Final-Only CLI Mode

The Desktop App is the primary, first-class experience for everyday users and shows **Live Previews** alongside longer sentence boundaries for natural readability. The text-only CLI is kept as a lightweight secondary mode for terminal workflows and testing; it disables **Live Previews** and cuts speech into shorter final-only segments (2–3 seconds) to reduce CPU usage while keeping output responsive.

## Consequences

- Visual and convenience features built for the Desktop App do not need to be mirrored in the CLI.
- Both modes share the same core audio capture, speech recognition, and **Transcript File** pipeline, differing only in segmentation timing and preview behavior.
