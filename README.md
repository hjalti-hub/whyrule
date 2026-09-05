# whyrule

### Claude isn't ignoring your CLAUDE.md. It never got it.

You wrote the rule down. You wrote it clearly. Claude does the opposite anyway,
and there's no error, no warning, nothing in the logs — so you rewrite the rule
in capitals and hope.

Usually the rule never arrived. Things that make text vanish between your file
and the model, none of which are visible by reading the file:

- an instruction inside an `<!-- HTML comment -->`, which is **stripped before
  injection**
- `@docs/setup.md` pointing at a file that moved — imports that resolve to
  nothing load nothing, and say nothing
- an `AGENTS.md` doing the work, which **Claude Code does not read**
- a `.claude/rules/` file whose `paths:` globs match no file in the repo, so it
  never loads
- your project rule and your `~/.claude/CLAUDE.md` rule flatly contradicting each
  other — they're concatenated, not overridden, so Claude picks one arbitrarily

`whyrule` finds all of it. There is nothing to install to try it:

```bash
git clone https://github.com/hjalti-hub/whyrule && cd whyrule
python3 -m whyrule
```

No API key. No model calls. No dependencies. Just `python3`.

Once you want it to run without being asked, install it properly and it
[hooks itself in](#running-itself) — after that you never type it again.

```console
$ whyrule

CLAUDE.md
  18: error REACH001  Instruction inside an HTML comment never reaches Claude: '- Always use `pnpm`, never `npm`, since the lockfile is p...'
      fix: Move the instruction outside the comment. Keep comments for notes meant only
      for human maintainers, which is what the stripping is for.
  3: error IMPORT001  `@docs/architecture.md` imports docs/architecture.md, which does not exist - nothing is loaded
      fix: Point it at a file that exists. Relative paths resolve against ./, the
      directory of the file the import is written in - not the working directory.
  4: error IMPORT001  `@CONVENTIONS.md` imports CONVENTIONS.md, which does not exist - nothing is loaded
      fix: Point it at a file that exists. Relative paths resolve against ./, the
      directory of the file the import is written in - not the working directory.
  8: warning IMPORT004  `@types/node` reads as a package scope, but is parsed as an import of a file that does not exist
      fix: Wrap it in backticks - `` `@types/node` `` keeps the text literal and stops
      it being read as an import.

  ... 14 more findings, across this file, AGENTS.md,
      .claude/rules/api.md and CLAUDE.local.md

5 error(s) · 12 warning(s) · 1 note(s) across 4 memory files (3 loaded at launch)
Run with --explain to see why each one matters.
```

And the question you actually have:

```console
$ whyrule why "run npm lint before committing"

Always run `npm run lint` before committing.
  CLAUDE.md:13  (project)
  This arrives, but something else in context disagrees.

  warning CONFLICT001  Contradicts an instruction in CLAUDE.md: 'Never run `npm run lint` before committing; it is too slow on...' against 'Always run `npm run lint` before committing.'
      why: All discovered memory files are concatenated into context rather than
      overriding each other, so both of these arrive together. The documentation is
      explicit about what happens next: if two rules contradict each other, Claude may
      pick one arbitrarily.
      fix: Delete one, or scope them apart so only one applies at a time - state the
      condition each holds under, or move the narrower one into a path-scoped
      `.claude/rules/` file.

  warning ENFORCE001  Promises to run at a fixed point, which CLAUDE.md cannot guarantee: 'Always run `npm run lint` before committing.'
      why: CLAUDE.md is context, not enforced configuration. The documentation's own
      answer for this shape of instruction is a hook: if the instruction is something
      that must run at a specific point, such as before every commit or after each file
      edit, write it as a hook instead. Hooks execute as shell commands at fixed
      lifecycle events and apply regardless of what Claude decides.
      fix: Move it to a hook - a PostToolUse hook on Edit|Write for after-edit work, or
      a PreToolUse hook on Bash for pre-commit work. Leave the reasoning here if it is
      worth the context.

  warning ENFORCE005  `npm run lint` cannot run - package.json defines no 'lint'
      why: An instruction naming a command that does not exist is followed by running it
      and watching it fail, which costs a turn every session. These usually date from a
      rename that updated the scripts and not the CLAUDE.md.
      fix: Update the command, or add the script to package.json.


Never run `npm run lint` before committing; it is too slow on this machine.
  CLAUDE.local.md:4  (local)
  This arrives, but something else in context disagrees.

  warning CONFLICT001  Contradicts an instruction in CLAUDE.md: 'Never run `npm run lint` before committing; it is too slow on...' against 'Always run `npm run lint` before committing.'
      why: All discovered memory files are concatenated into context rather than
      overriding each other, so both of these arrive together. The documentation is
      explicit about what happens next: if two rules contradict each other, Claude may
      pick one arbitrarily.
      fix: Delete one, or scope them apart so only one applies at a time - state the
      condition each holds under, or move the narrower one into a path-scoped
      `.claude/rules/` file.

  warning ENFORCE001  Promises to run at a fixed point, which CLAUDE.md cannot guarantee: 'Never run `npm run lint` before committing; it is too slow on this mac'
      why: CLAUDE.md is context, not enforced configuration. The documentation's own
      answer for this shape of instruction is a hook: if the instruction is something
      that must run at a specific point, such as before every commit or after each file
      edit, write it as a hook instead. Hooks execute as shell commands at fixed
      lifecycle events and apply regardless of what Claude decides.
      fix: Move it to a hook - a PostToolUse hook on Edit|Write for after-edit work, or
      a PreToolUse hook on Bash for pre-commit work. Leave the reasoning here if it is
      worth the context.

  warning ENFORCE005  `npm run lint` cannot run - package.json defines no 'lint'
      why: An instruction naming a command that does not exist is followed by running it
      and watching it fail, which costs a turn every session. These usually date from a
      rename that updated the scripts and not the CLAUDE.md.
      fix: Update the command, or add the script to package.json.


Run `npm run typecheck` after each file edit.
  CLAUDE.md:14  (project)
  This arrives, but CLAUDE.md cannot guarantee it.

  warning ENFORCE001  Promises to run at a fixed point, which CLAUDE.md cannot guarantee: 'Run `npm run typecheck` after each file edit.'
      why: CLAUDE.md is context, not enforced configuration. The documentation's own
      answer for this shape of instruction is a hook: if the instruction is something
      that must run at a specific point, such as before every commit or after each file
      edit, write it as a hook instead. Hooks execute as shell commands at fixed
      lifecycle events and apply regardless of what Claude decides.
      fix: Move it to a hook - a PostToolUse hook on Edit|Write for after-edit work, or
      a PreToolUse hook on Bash for pre-commit work. Leave the reasoning here if it is
      worth the context.
```

Three different reasons one rule isn't being followed, none of which produce an
error anywhere.

## What actually loads

Memory files do not override each other — they are concatenated, root-first, and
all of it arrives before your first message. `whyrule list` shows the pile:

```console
$ whyrule list
   CLAUDE.md             project                       28 lines
   .claude/rules/api.md  project rule                  10 lines
   CLAUDE.local.md       local                         5 lines
 · AGENTS.md             not read by Claude Code       5 lines

43 lines load at launch.
Lines marked · are not in the launch context.
```

## Running itself

A linter you have to remember to run is a linter you stop running. `whyrule`
registers itself as a Claude Code hook, so the harness runs it instead of you:

```bash
whyrule install          # this project
whyrule install --user   # every project on this machine
```

That writes two entries into `settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "whyrule hook",
            "timeout": 20,
            "statusMessage": "Checking memory files…"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "whyrule hook",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**`PostToolUse`** fires the moment a `CLAUDE.md`, a `CLAUDE.local.md` or a
`.claude/rules/*.md` is written. On an error it exits 2, which puts the message
in front of Claude in the same turn — so a rule written into an HTML comment
gets caught by the turn that wrote it.

**`SessionStart`** fires when a session opens, and its stdout is injected as
context. Claude is told which of its own instructions never arrived. That is the
one piece of information it cannot work out for itself.

Both are silent when nothing is wrong, so a healthy setup costs no context.

`whyrule install --print` shows the resulting file without writing it,
`--status` reports whether it's in, and `--uninstall` takes it back out. Your
existing hooks are preserved and the previous file is backed up.

If `whyrule` isn't importable from outside its own checkout, `install` **refuses
to write the hook** and tells you why — a hook that silently never runs is
exactly the failure this tool exists to catch.

## Why another CLAUDE.md linter?

Most of them check style: heading structure, word counts, whether you used
bullets. Useful, but a well-structured rule that never reaches the model is
still a rule that never reaches the model.

`whyrule` only reports things that change **whether an instruction arrives or
can be acted on**, and every rule is traceable to documented Claude Code
behaviour:

- It reads the **whole loaded set** — managed policy, `~/.claude/CLAUDE.md`,
  `~/.claude/rules/`, every ancestor directory, the project file, the local
  file, `.claude/rules/`. A contradiction is a fact about two files; you cannot
  see it from either one.
- It follows **imports** the way the loader does: skipping code spans and
  fences, resolving relative paths against the importing file rather than the
  working directory, and stopping at four hops.
- It reads your **settings**, because a `claudeMdExcludes` glob in a layer you
  didn't write can drop your file with no sign in the session.
- It never estimates. Sizes and line counts are measured; there are no invented
  token numbers anywhere in the output.

## Install

Try it with no install at all:

```bash
git clone https://github.com/hjalti-hub/whyrule && cd whyrule
python3 -m whyrule
```

To use it anywhere, and to install the hooks:

```bash
pipx install git+https://github.com/hjalti-hub/whyrule
# or
pip install git+https://github.com/hjalti-hub/whyrule
```

Python 3.9+. No dependencies.

## Use

```bash
whyrule                          # this project plus your personal memory files
whyrule list                     # what loads, in the order it is concatenated
whyrule why "always use pnpm"    # why one instruction is not landing
whyrule rules                    # every rule, grouped
whyrule --explain                # the documented behaviour behind each finding
whyrule --json                   # machine-readable
whyrule --sarif > out.sarif      # CI annotations
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--no-user` | Skip `~/.claude`. Contradictions with your personal rules go undetected. |
| `--no-subdirs` | Skip `CLAUDE.md` files in subdirectories. |
| `--project PATH` | Resolve memory files and `paths:` globs against another root. |
| `--overlap N` | Similarity threshold for the CONFLICT rules, 0..1 (default `0.45`). |
| `--disable IDS` | Suppress rules, e.g. `--disable WEIGHT002,ENFORCE003`. |
| `--fail-on LEVEL` | Lowest severity that exits non-zero (default `error`). |

## What it checks

Every rule below describes a failure that produces **no error message**. Run
`whyrule rules` for the same list in the terminal.

### Loading — does the file reach Claude at all?

| Rule | |
| --- | --- |
| `LOAD000` | Memory file cannot be read |
| `LOAD001` | File is over the 4 MiB limit, so Claude Code skips it whole |
| `LOAD002` | A `claudeMdExcludes` pattern in settings quietly excludes this file |
| `LOAD003` | An instruction file Claude Code does not read, with no CLAUDE.md importing it |
| `LOAD004` | `claudeMd` is set in a settings layer where the key has no effect |

`LOAD001` is the one people don't believe: past 4 MiB the file is not truncated,
it is skipped entirely.

### Reach — does the text inside it survive to context?

| Rule | |
| --- | --- |
| `REACH001` | An instruction sits in an HTML comment, which is stripped before injection |

Block-level HTML comments are removed before the file becomes context. Comments
inside fenced code blocks are kept — and when you open the file with the Read
tool, the comment is visible again, which is why this one survives review.

### Imports — do the `@` references resolve?

| Rule | |
| --- | --- |
| `IMPORT001` | `@import` target does not exist, so it contributes nothing |
| `IMPORT002` | Import sits deeper than four hops and never enters context |
| `IMPORT003` | Imports form a cycle |
| `IMPORT004` | Prose that reads as a package scope or handle is parsed as an import |
| `IMPORT005` | A project import resolves outside the working directory and needs approval |

`IMPORT004` catches the sentence you didn't know was code. Import parsing skips
code spans and fenced blocks *and nothing else*, so writing `we pin @types/node`
in prose is an import attempt. Backticks make it literal.

### Scoping — does a path-scoped rule ever match?

| Rule | |
| --- | --- |
| `SCOPE001` | `paths:` globs match no file in the project, so the rule never loads |
| `SCOPE002` | `paths:` brace expansion exceeds its 1,000-pattern budget and matches nothing |
| `SCOPE003` | A `paths:` pattern has an unclosed `[`, so it matches nothing |

The usual cause of `SCOPE001` is `*` not crossing directory separators:
`src/*.ts` misses `src/api/handler.ts`, which `src/**/*.ts` matches.

### Conflict — do two instructions fight each other?

| Rule | |
| --- | --- |
| `CONFLICT001` | Two loaded instructions about one subject contradict each other |
| `CONFLICT002` | One setting is given two different values |
| `CONFLICT003` | The same instruction is repeated in two loaded files |

The documentation states the consequence outright: *"if two rules contradict
each other, Claude may pick one arbitrarily."* Nothing overrides anything —
your personal file and your project file both arrive.

### Enforceability — can the instruction be acted on?

| Rule | |
| --- | --- |
| `ENFORCE001` | A guarantee about when something runs, which only a hook can make |
| `ENFORCE002` | An absolute prohibition, which only permissions or a hook can enforce |
| `ENFORCE003` | An instruction with nothing concrete enough to verify |
| `ENFORCE004` | References a path that does not exist |
| `ENFORCE005` | Tells Claude to run a command the project does not define |

`ENFORCE001` and `ENFORCE002` are not style opinions. CLAUDE.md is delivered as
a user message, not as configuration — "always run the tests before committing"
is a request, and the documentation's own answer for that shape of instruction
is to write it as a hook. `whyrule` tells you which of your rules are wearing
the wrong mechanism.

### Weight — is there too much of it to follow?

| Rule | |
| --- | --- |
| `WEIGHT001` | File is over the documented 200-line target, which reduces adherence |
| `WEIGHT002` | Launch-loaded memory is large enough to compete with itself |
| `WEIGHT003` | Imports load at launch too, so splitting the file did not reduce context |

`WEIGHT003` exists because splitting a long CLAUDE.md into `@` imports feels
like it should help and does not: imported files are expanded into context at
launch. `.claude/rules/` with `paths:` frontmatter is the mechanism that
actually defers loading.

## In CI

```yaml
name: claude-md
on: [push, pull_request]
jobs:
  whyrule:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pipx install git+https://github.com/hjalti-hub/whyrule
      - run: whyrule --no-user --fail-on warning
```

For inline annotations on the diff, emit SARIF and upload it:

```yaml
      - run: whyrule --no-user --sarif --fail-on never > whyrule.sarif
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: whyrule.sarif
```

Pass `--no-user` in CI: there is no `~/.claude` on a runner, and the machine's
personal rules aren't the repository's business.

## Examples

`examples/broken/` is a small project carrying one instance of most failure
modes, each broken on purpose and each verified by CI to still be broken:

```console
$ whyrule --project examples/broken --no-user
5 error(s) · 12 warning(s) · 1 note(s) across 4 memory files (3 loaded at launch)
```

`examples/clean/` is the same shape with nothing wrong. Both are worth reading —
the broken one looks completely fine.

## Library use

```python
import whyrule

files, findings = whyrule.check(project=".")
for finding in findings:
    print(finding.rule, finding.severity.value, finding.path, finding.message)
```

## Contributing

The bar for a new rule is specific: it must describe a failure that produces
**no error message**, and it must be traceable to documented Claude Code
behaviour. Rules encoding a preference belong in a style linter instead.

If you add one, add its documented basis to `whyrule/spec.py`, its summary to
`whyrule/rules/catalog.py`, and a test asserting both directions — that it fires
on the broken case and stays silent on the reasonable one. A rule that only
proves it fires is how a linter becomes noise.

```bash
python3 -m unittest discover -s tests -t .
python3 tests/check_catalog.py
```

## Accuracy

If a rule here contradicts Claude Code's actual behaviour, that is a bug worth
reporting — the value of this tool is entirely in being right about mechanics.
Behaviour also changes between versions; every rule is derived from the memory
documentation as of September 2026, and `whyrule/spec.py` records the sentence
each constant comes from.

## Related

- [whyskill](https://github.com/hjalti-hub/whyskill) — the same idea for skills
  that never load, never get chosen, or are shadowed by another skill.
- [deadweight](https://github.com/hjalti-hub/deadweight) — finds the skills,
  subagents and MCP servers that load every session and are never used.

## License

MIT
