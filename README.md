# Kairos

An NUS course optimiser. Searches every valid combination of your modules' tutorial/lab/recitation/sectional
slots, scores them against your preferences, and prints:

1. the top-N timetables (with NUSMods share links),
2. ranked backup choices per balloted group, and
3. a snake-order ballot ranking (max 20 entries) ready for tutorial registration.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -e .

## Usage

Generate a config from your NUSMods share URL (prompts for per-component
difficulty ratings and module priority):

    .venv/bin/kairos init "https://nusmods.com/timetable/sem-1/share?CS1231S=TUT:07A,LEC:2&..."

Tweak `config.yaml` (preferences, weights, balloted types), then:

    .venv/bin/kairos run

## Interactive app

    .venv/bin/kairos tui "https://nusmods.com/timetable/sem-1/share?CS1231S=TUT:07A,LEC:2&..."
    # or, to resume from a saved config:
    .venv/bin/kairos tui

A full-screen app: tabs on the left for Weights, Difficulty, Times, and Priority
(adjust with ←/→); the timetables and their score breakdown on the right, re-ranking
live as you tune. The Classes pane lists every group offering more than one
timeslot — including lectures, which some modules run as two alternative classes
(a different time, or the same time online). Press `→` to see that group's
timeslots and `l` to lock one. Locking pins the slot, not the class number, so
interchangeable twins stay available for the ballot; by default lectures are never
balloted and never appear in `ballot.txt`. Press `b` for the ballot view, `s` to save
config.yaml, `e` to export the ballot to `ballot.txt`, `c` to copy the selected
timetable's NUSMods link, `q` to quit.

## How scoring works

Weighted sum of: class time outside your preferred window, per-day difficulty
overload, lecture+tutorial same-day pairing, free days, gaps between classes,
and lunch-break availability. Online lessons (venue `E-Learn_*`) don't count
against physical-presence criteria but do count toward daily difficulty.

Weights and thresholds live under `preferences:` in `config.yaml`.
