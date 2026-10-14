# Git Commit Guidelines

To maintain a clean and readable project history, we follow the **Conventional Commits** specification.

---

## Commit Format

`<type>(<scope>): <short description>`

---

## Commit Types (`<type>`)

* **`feat`** — A new feature (e.g., new API, UI screen, or business logic)
* **`fix`** — A bug fix in code or hardware schematics
* **`hardware`** (or `hw`) — Hardware schematics, TinkerCAD models, or `.ino` sketches
* **`docs`** — Documentation updates (README, architecture specs)
* **`refactor`** — Code restructuring without changing functionality
* **`chore`** — Maintenance tasks (`.github` config, `.gitignore`, dependencies)
* **`test`** — Adding or updating test cases

---

## Scopes (`<scope>`)

* `backend` — Core Backend service
* `mobile` — React Native application
* `ocr` — License plate recognition service
* `bridge` — PySerial hardware gateway (Arduino ↔ Backend)
* `arduino` — Arduino C++ firmware sketches
* `tinkercad` — 3D models and breadboard schematics
* `docs` — Project documentation
* `github` —`.github` workflows, templates, and configurations

---

## Examples

```text
feat(bridge): add automatic reconnection handler for COM port
hardware(step-03): add 2 SG90 servo motors to TinkerCAD schematic
fix(mobile): resolve QR payment display issue on exit screen
docs(readme): update Mermaid sequence diagram and license
chore(github): configure CODEOWNERS and PR templates