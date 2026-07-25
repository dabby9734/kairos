# `kairos advise <nusmods-link>` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kairos advise <link>` parses an NUSMods share link, asks for year of study, round, and per-course tier, writes `coursereg.yaml`, then launches the advisor TUI immediately.

**Architecture:** All new code lives in `kairos/cli.py` (the I/O layer): a generic `_prompt_choice` input helper, an `_advise_setup` flow that reuses the existing `parse_share_url`, `profile_from_dict`, and `profile_to_yaml`, and a two-line branch in `cmd_advise`. The pure core (`kairos/coursereg/model.py` etc.) is not modified.

**Tech Stack:** Python 3.11+, argparse, PyYAML, pytest (monkeypatched `builtins.input`, per `tests/test_cli_init.py` precedent).

Spec: `docs/superpowers/specs/2026-07-25-advise-from-link-design.md`

## Global Constraints

- No I/O in the pure core — prompts and file writes stay in `kairos/cli.py`.
- User-facing errors are `raise SystemExit("error: ...")`.
- Candidate order is link order (insertion order from `parse_share_url`) — deliberate, not a sort; no tiebreak needed.
- Prompt defaults: seniority `2`, round `2`, tier `major`. Tier shorthands `c`/`m`/`u`.
- Special-term links (`sem-3`/`sem-4`) must fail **before** any prompt is issued.
- Existing `coursereg.yaml` → `overwrite? [y/N]`, anything but `y` → `SystemExit("aborted")`.
- Run tests with `.venv/bin/pytest -q` from the repo root; all must pass.
- Docs upkeep rule: CLI change ships with user-guide / CLAUDE.md / development.md / architecture.md updates (Task 4, same plan).

---

### Task 1: `_prompt_choice` helper

**Files:**
- Modify: `kairos/cli.py` (add helper after `_prompt_difficulty`, around line 60)
- Test: `tests/test_coursereg_cli.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_prompt_choice(prompt: str, valid: dict, default: str) -> str` — loops on `input()`; empty answer returns `default`; otherwise the lowercased, stripped answer is looked up in `valid` (a mapping of accepted input → canonical value); unrecognized input prints a hint and reprompts. Task 2 calls it for seniority, round, and tiers.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_coursereg_cli.py`:

```python
def test_prompt_choice_default_shorthand_and_reprompt(monkeypatch, capsys):
    from kairos.cli import _prompt_choice

    tier_choices = {
        "core": "core", "major": "major", "ue": "ue",
        "c": "core", "m": "major", "u": "ue",
    }
    answers = iter(["", "U", "core!", "c"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert _prompt_choice("tier? ", tier_choices, "major") == "major"  # bare Enter
    assert _prompt_choice("tier? ", tier_choices, "major") == "ue"  # shorthand, any case
    # "core!" is rejected with a hint, then "c" is accepted
    assert _prompt_choice("tier? ", tier_choices, "major") == "core"
    assert "core, major, ue" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_coursereg_cli.py::test_prompt_choice_default_shorthand_and_reprompt -q`
Expected: FAIL — `ImportError: cannot import name '_prompt_choice'`

- [ ] **Step 3: Write the implementation**

In `kairos/cli.py`, directly after `_prompt_difficulty` (line 52-59):

```python
def _prompt_choice(prompt: str, valid: dict, default: str) -> str:
    # `valid` maps accepted (lowercase) input to its canonical value, so
    # shorthands like "c" -> "core" ride along for free.
    while True:
        answer = input(prompt).strip().lower()
        if not answer:
            return default
        if answer in valid:
            return valid[answer]
        print(f"please enter one of: {', '.join(sorted(set(valid.values())))}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_coursereg_cli.py::test_prompt_choice_default_shorthand_and_reprompt -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kairos/cli.py tests/test_coursereg_cli.py
git commit -m "feat: add _prompt_choice input helper for advise setup"
```

---

### Task 2: `_advise_setup` flow

**Files:**
- Modify: `kairos/cli.py` (add after `_prompt_choice`)
- Test: `tests/test_coursereg_cli.py`

**Interfaces:**
- Consumes: `parse_share_url(url)` (existing, `kairos/cli.py:23`) → `(semester: int, selections: dict[str, dict])`; `_prompt_choice` from Task 1; `profile_from_dict(data, source)` and `profile_to_yaml(profile)` from `kairos/coursereg/model.py`.
- Produces: `_advise_setup(url: str, config_path: Path) -> Profile` — prompts, writes `config_path`, prints `wrote <path>`, returns the built `Profile`. Task 3 calls it from `cmd_advise`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_coursereg_cli.py` (also add `import yaml` and `from pathlib import Path` at the top of the file):

```python
ADVISE_URL = (
    "https://nusmods.com/timetable/sem-2/share?"
    "CS2109S=TUT:01,LEC:1&GEH1049=&MA2001=LEC:2"
)


def test_advise_setup_writes_profile_in_link_order(tmp_path, monkeypatch, capsys):
    from kairos.cli import _advise_setup

    # seniority, round, then one tier per course in link order
    answers = iter(["3", "3", "c", "", "u"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    config_path = tmp_path / "coursereg.yaml"
    profile = _advise_setup(ADVISE_URL, config_path)

    written = yaml.safe_load(config_path.read_text())
    assert written["seniority"] == 3
    assert written["semester"] == 2  # from the link, never prompted
    assert written["round"] == 3
    assert written["ranked"] is False
    assert written["candidates"] == {"CS2109S": "core", "GEH1049": "major", "MA2001": "ue"}
    assert list(written["candidates"]) == ["CS2109S", "GEH1049", "MA2001"]  # link order
    assert profile.order == ["CS2109S", "GEH1049", "MA2001"]
    assert f"wrote {config_path}" in capsys.readouterr().out


def test_advise_setup_all_defaults(tmp_path, monkeypatch):
    from kairos.cli import _advise_setup

    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    profile = _advise_setup(ADVISE_URL, tmp_path / "coursereg.yaml")
    assert profile.seniority == 2
    assert profile.round == 2
    assert set(profile.tiers.values()) == {"major"}


def test_advise_setup_declined_overwrite_aborts(tmp_path, monkeypatch):
    from kairos.cli import _advise_setup

    config_path = tmp_path / "coursereg.yaml"
    config_path.write_text("existing: true")
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(SystemExit, match="aborted"):
        _advise_setup(ADVISE_URL, config_path)
    assert config_path.read_text() == "existing: true"


def test_advise_setup_rejects_special_term_before_prompting(tmp_path, monkeypatch):
    from kairos.cli import _advise_setup

    def no_prompts(prompt=""):
        raise AssertionError("prompted despite special-term link")

    monkeypatch.setattr("builtins.input", no_prompts)
    url = "https://nusmods.com/timetable/sem-3/share?CS2109S=TUT:01"
    with pytest.raises(SystemExit, match="special term"):
        _advise_setup(url, tmp_path / "coursereg.yaml")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_cli.py -q`
Expected: the four new tests FAIL — `ImportError: cannot import name '_advise_setup'`; the two pre-existing tests still pass.

- [ ] **Step 3: Write the implementation**

In `kairos/cli.py`, directly after `_prompt_choice`:

```python
def _advise_setup(url: str, config_path: Path):
    # Lazy import, matching cmd_advise: the coursereg stack stays unloaded
    # for the timetable subcommands.
    from .coursereg.model import profile_from_dict, profile_to_yaml

    if config_path.exists():
        answer = input(f"{config_path} already exists — overwrite? [y/N] ").strip().lower()
        if answer != "y":
            raise SystemExit("aborted")
    semester, selections = parse_share_url(url)
    if semester not in (1, 2):
        raise SystemExit(
            "error: kairos advise models semesters 1 and 2 only — "
            "this link is for a special term"
        )
    seniority = int(_prompt_choice("year of study (1-4) [2]: ", {c: c for c in "1234"}, "2"))
    rnd = int(_prompt_choice("round (2/3) [2]: ", {"2": "2", "3": "3"}, "2"))
    tier_choices = {
        "core": "core", "major": "major", "ue": "ue",
        "c": "core", "m": "major", "u": "ue",
    }
    candidates = {
        code: _prompt_choice(f"tier for {code} (core/major/ue) [major]: ", tier_choices, "major")
        for code in selections  # link order — becomes the initial rank order
    }
    profile = profile_from_dict(
        {"seniority": seniority, "semester": semester, "round": rnd, "candidates": candidates},
        source=str(config_path),
    )
    config_path.write_text(profile_to_yaml(profile))
    print(f"wrote {config_path}")
    return profile
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_coursereg_cli.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add kairos/cli.py tests/test_coursereg_cli.py
git commit -m "feat: interactive coursereg.yaml setup from an NUSMods share link"
```

---

### Task 3: CLI wiring — optional `share_url` on `advise`

**Files:**
- Modify: `kairos/cli.py` (`cmd_advise`, line 200-208; `advise` subparser, line 249-267)
- Test: `tests/test_coursereg_cli.py`

**Interfaces:**
- Consumes: `_advise_setup` from Task 2; existing `load_profile`, `load_history`, `run_advisor`, `AdvisorState`.
- Produces: `kairos advise [share_url]` CLI behavior. No later task depends on new symbols.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_coursereg_cli.py`:

```python
def test_advise_with_link_generates_config_then_launches_tui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    answers = iter(["1", "2", "m", "core", "ue"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(
        "kairos.coursereg.fetch.load_history", lambda cache_dir, refetch=False: []
    )
    captured = {}
    monkeypatch.setattr(
        "kairos.coursereg.tui.app.run_advisor",
        lambda state, config_path: captured.update(
            profile=state.profile, config_path=config_path
        ),
    )

    main(["advise", ADVISE_URL])

    written = yaml.safe_load(Path("coursereg.yaml").read_text())
    assert written["candidates"] == {"CS2109S": "major", "GEH1049": "core", "MA2001": "ue"}
    assert captured["profile"].semester == 2
    assert captured["profile"].seniority == 1
    assert captured["config_path"] == Path("coursereg.yaml")


def test_advise_without_link_still_loads_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("coursereg.yaml").write_text(
        "seniority: 2\nsemester: 1\nround: 2\ncandidates:\n  CS2109S: major\n"
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("prompted"))
    monkeypatch.setattr(
        "kairos.coursereg.fetch.load_history", lambda cache_dir, refetch=False: []
    )
    captured = {}
    monkeypatch.setattr(
        "kairos.coursereg.tui.app.run_advisor",
        lambda state, config_path: captured.update(profile=state.profile),
    )

    main(["advise"])

    assert captured["profile"].tiers == {"CS2109S": "major"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_coursereg_cli.py -q`
Expected: `test_advise_with_link_generates_config_then_launches_tui` FAILS — argparse exits with `unrecognized arguments` (SystemExit 2). `test_advise_without_link_still_loads_profile` may already pass; that's fine — it pins the unchanged path.

- [ ] **Step 3: Write the implementation**

In `kairos/cli.py`, replace the body of `cmd_advise` (line 200-208):

```python
def cmd_advise(args) -> None:
    from .coursereg.fetch import load_history
    from .coursereg.model import load_profile
    from .coursereg.tui.app import run_advisor
    from .coursereg.tui.state import AdvisorState

    config_path = Path(args.config)
    if args.share_url:
        profile = _advise_setup(args.share_url, config_path)
    else:
        profile = load_profile(config_path)
    records = load_history(Path(args.cache_dir), refetch=args.refetch)
    run_advisor(AdvisorState(profile, records), config_path)
```

In `main()`, add to the `advise` subparser (after the `advise_parser = subparsers.add_parser(...)` block, before the `--config` argument):

```python
    advise_parser.add_argument(
        "share_url", nargs="?",
        help="NUSMods share URL — asks setup questions and writes coursereg.yaml first",
    )
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all PASS (full suite, not just this file — `cmd_advise` and the parser are shared surface).

- [ ] **Step 5: Commit**

```bash
git add kairos/cli.py tests/test_coursereg_cli.py
git commit -m "feat: kairos advise <share-url> — setup questions then straight into the TUI"
```

---

### Task 4: Docs

**Files:**
- Modify: `docs/user-guide.md` (advisor section, ~line 386-429)
- Modify: `CLAUDE.md` (line 10, `advise` command)
- Modify: `docs/development.md` (line 38, `test_coursereg_cli.py` row)
- Modify: `docs/architecture.md` (~line 76, `cmd_advise` description)

**Interfaces:** none — prose only.

- [ ] **Step 1: user-guide — coursereg.yaml reference intro**

In `docs/user-guide.md`, replace the paragraph at line 388-391:

```markdown
`kairos advise` reads `coursereg.yaml` (not `config.yaml`) from the current
directory by default. There's no `init` step for it — if the file is
missing, it exits with an error that pastes this exact template so you can
copy it straight in:
```

with:

```markdown
`kairos advise` reads `coursereg.yaml` (not `config.yaml`) from the current
directory by default. You don't have to write it by hand: run
`kairos advise <nusmods-share-url>` and it is generated for you (see
"Running it" below). If the file is missing and no link is given, the
command exits with an error that pastes this exact template so you can
copy it straight in:
```

- [ ] **Step 2: user-guide — "Running it" section**

In `docs/user-guide.md`, replace the block at line 419-425:

```markdown
### Running it

    .venv/bin/kairos advise
    # or, to use a different file/cache location:
    .venv/bin/kairos advise --config coursereg.yaml --cache-dir data/coursereg
    # if you suspect the cached demand data is stale or broken:
    .venv/bin/kairos advise --refetch
```

with:

```markdown
### Running it

    # first time: generate coursereg.yaml from an NUSMods share link
    .venv/bin/kairos advise 'https://nusmods.com/timetable/sem-1/share?...'
    # after that (or with a hand-written coursereg.yaml):
    .venv/bin/kairos advise
    # or, to use a different file/cache location:
    .venv/bin/kairos advise --config coursereg.yaml --cache-dir data/coursereg
    # if you suspect the cached demand data is stale or broken:
    .venv/bin/kairos advise --refetch

With a link, the semester and course codes come from the link itself (the
lesson picks in it are ignored) and you're asked for everything else: your
year of study `[2]`, the round `[2]`, and each course's tier
(`core`/`major`/`ue`, default `major`, shorthands `c`/`m`/`u`). The file is
written and the TUI opens immediately with your fresh profile. If
`coursereg.yaml` already exists you're asked before it's overwritten
(this discards any saved ranking); special-term links (`sem-3`/`sem-4`)
are rejected up front since the advisor models semesters 1 and 2 only.
```

- [ ] **Step 3: CLAUDE.md**

Replace line 10:

```markdown
- advise: `.venv/bin/kairos advise` (CourseReg R2/R3 ranking advisor)
```

with:

```markdown
- advise: `.venv/bin/kairos advise [share-url]` (CourseReg R2/R3 ranking
  advisor; with an NUSMods link, generates coursereg.yaml via prompts first)
```

- [ ] **Step 4: development.md test table**

In `docs/development.md` line 38, replace the `test_coursereg_cli.py` row's description:

```markdown
| `test_coursereg_cli.py` | `kairos/cli.py` (`advise` subcommand) | That a missing `coursereg.yaml` exits with the pasted `TEMPLATE`, and that `advise` defaults `--config`/`--cache-dir` to `coursereg.yaml`/`data/coursereg` rather than the timetable subcommands' `config.yaml`/`data/cache`. |
```

with:

```markdown
| `test_coursereg_cli.py` | `kairos/cli.py` (`advise` subcommand) | That a missing `coursereg.yaml` exits with the pasted `TEMPLATE`; that `advise` defaults `--config`/`--cache-dir` to `coursereg.yaml`/`data/coursereg` rather than the timetable subcommands' `config.yaml`/`data/cache`; and the `advise <share-url>` setup flow — prompt defaults/shorthands/reprompts, link-order candidates, overwrite confirmation, special-term rejection before any prompt, and that the TUI then launches with the fresh profile. |
```

- [ ] **Step 5: architecture.md**

In `docs/architecture.md` line 76-78, replace:

```markdown
the `cli.py` entrypoint. `cli.cmd_advise` loads `coursereg.yaml` into a
`Profile` (`coursereg.model.load_profile`), loads the permanently-cached
demand history (`coursereg.fetch.load_history`), and hands both to
```

with:

```markdown
the `cli.py` entrypoint. `cli.cmd_advise` loads `coursereg.yaml` into a
`Profile` (`coursereg.model.load_profile`) — or, given an NUSMods share
link, first generates that file through `cli._advise_setup`'s prompts
(I/O stays in the CLI layer) — loads the permanently-cached
demand history (`coursereg.fetch.load_history`), and hands both to
```

- [ ] **Step 6: Run the full suite and commit**

Run: `.venv/bin/pytest -q`
Expected: all PASS (docs changes can't break tests; this is the pre-commit gate).

```bash
git add docs/user-guide.md CLAUDE.md docs/development.md docs/architecture.md
git commit -m "docs: document kairos advise <share-url> setup flow"
```
