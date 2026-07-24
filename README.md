# Kairos

An NUS timetable optimiser. Searches every valid combination of your modules'
tutorial/lab/recitation/sectional slots, scores them against your preferences,
and produces: the top-N timetables (with NUSMods share links), ranked backup
choices per balloted group, and a ready-to-submit 20-slot ballot ranking in
snake order.

## Quickstart

    python3 -m venv .venv
    .venv/bin/pip install -e .
    .venv/bin/kairos init "https://nusmods.com/timetable/sem-1/share?..."
    .venv/bin/kairos run          # print timetables + ballot
    .venv/bin/kairos tui          # or tune everything live

## Documentation

| If you want to… | Read |
|---|---|
| use kairos (config, TUI, reading the ballot) | [docs/user-guide.md](docs/user-guide.md) |
| understand how the code works | [docs/architecture.md](docs/architecture.md) |
| set up a dev environment and run tests | [docs/development.md](docs/development.md) |
