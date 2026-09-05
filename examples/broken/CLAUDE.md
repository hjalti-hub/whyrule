# Acme API

Project overview lives in @docs/architecture.md and the conventions in
@CONVENTIONS.md.

## Setup

Install dependencies with `npm install`. We pin @types/node deliberately, so
do not upgrade it without checking the build.

## Workflow

- Always run `npm run lint` before committing.
- Run `npm run typecheck` after each file edit.
- Use 2-space indentation in TypeScript files.
- Never force-push to main.

<!--
- Always use `pnpm`, never `npm`, since the lockfile is pnpm's.
- Keep secrets in `.dev.vars`.
-->

## Layout

API handlers live in `src/api/handlers/`, and shared types in `src/types.ts`.

Write good code and follow best practices.
