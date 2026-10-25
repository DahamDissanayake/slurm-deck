# UI polish and About page: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo each task below is one SerenEdge task and one PR into `dev`.

**Goal:** Controls that line up on every page, single-line panels, an icon top bar, and a public About page.

**Architecture:**
- One `controls.ts` module holds every text box, select and button style. Each has a fixed height and no margin, and pages pick named variants instead of overriding classes.
- One `icons.tsx` holds small inline-SVG icons, used by the top bar.
- `/about` is a static public page that renders without `AppShell`.

**Tech Stack:** React 18 + TypeScript + Vite, Tailwind with the project's colour tokens, Vitest + Testing Library.

**Spec:** `docs/specs/2026-10-25-ui-polish-and-about-design.md`

## Global Constraints

- No new dependencies: icons are inline SVG with `stroke="currentColor"`.
- Colour classes come only from the tokens in `design-tokens-and-motifs` (`bg-bg`, `bg-surface`, `bg-surface-2`, `border-border`, `text-text`, `text-text-dim`, `text-accent`, `text-danger`, `text-warning`, `text-ok`).
- Every icon button keeps an accessible name equal to the old text: "Light theme" or "Dark theme", "Change password", "Sign out".
- Never combine a preset with a class for the same property. A variant is its own named preset.
- Frontend CI passes: `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` (all in `frontend/`), then `serenedge ci` before pushing.
- Commits are `SLURM-<n>: <summary>`, with no AI attribution.

## Review Focus

1. **Dark and light themes.** Every changed control and icon stays visible and keeps contrast in both themes. Check each page in both with the theme toggle.
2. **Keyboard users.** Icon buttons and links get a visible focus ring (`focus-visible:outline`). Test: Task 2 asserts the focus classes.
3. **Disabled buttons.** Every button preset keeps `disabled:opacity-50`, so disabled controls still look disabled. Test: Task 1 asserts it on every button preset.
4. **Signed-out `/about`.** It must not bounce to `/sign-in`. Test: Task 3 renders it against a 401 `/api/auth/me` and asserts the URL is still `/about`.
5. **Narrow screens.** Rows of controls wrap rather than overflow (`flex-wrap`) at phone width. The reviewer checks `/notify`, `/jobs` and `/admin/users/new` at 375px.

---

## Task 1: One set of control styles and the alignment pass

SerenEdge: **SLURM-55** (part 1 of 3)

**Files:**
- Create: `frontend/src/components/controls.ts`, `frontend/src/components/controls.test.ts`
- Remove: `frontend/src/components/buttons.ts`. Its users import from `controls.ts`.
- Modify:
  - the presets in `pages/PublicPage.tsx` (`Field`, `button`), `pages/admin/AdminLayout.tsx` (`inputClass`, `smallButton`, `primaryButton`) and `pages/NewJob/StepInputs.tsx` (`field`, `primary`, `secondary`): delete them and import from `controls.ts`. Keep the old names as re-exports only if that keeps the diff smaller.
  - every file that uses these presets or has its own control classes. Find them with `grep -rnE "<(input|select|textarea|button)|className=\{\`\\$\{" frontend/src --include=*.tsx`. The known overrides are in `Notify.tsx`, `NewJob/StepReview.tsx`, `NewJob/StepInputs.tsx`, `Files.tsx`, `admin/UserDetail.tsx`, `admin/Users.tsx`, `Environments.tsx`, `UploadPanel.tsx` and `FilePicker.tsx` (`select ... p-1`).
- Test: `frontend/src/pages/Notify.test.tsx` (new)

**Interfaces:**
- Produces (`components/controls.ts`, all `string`):
  - `input`, `select`, `textarea`: height `h-10` (textarea: `min-h-20`), `rounded-sm border border-border bg-surface-2 px-3 text-base text-text`, no margin, no width.
  - `primary`: `h-10 rounded-sm border border-transparent bg-accent px-4 font-semibold text-bg disabled:opacity-50`.
  - `secondary`: `h-10 rounded-sm border border-border px-4 text-text hover:border-accent disabled:opacity-50`.
  - `danger`: like `secondary`, with `text-danger hover:border-danger`.
  - `small`: `h-8 rounded-sm border border-border px-3 text-sm text-text hover:border-accent disabled:opacity-50`.
  - `smallDanger`: like `small`, with `text-danger`.
  - `full = "w-full"`, used as `` `${input} ${full}` ``. Adding a class for a different property is allowed.
  - `inputRow = "flex flex-wrap items-end gap-2"`, for a labelled input plus buttons on one line.
- Produces: `Field` in `PublicPage.tsx` keeps its signature `Field({ label, ...input })` and uses `` `${input} ${full}` ``. The label sits above it in its own element, and spacing comes from a wrapping `mb-4` div.
- Produces: `PRESETS: Record<string, string>`, exported from `controls.ts` for the tests.

- [ ] **Step 1: Write the failing tests** in `components/controls.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { PRESETS, input, select, primary, secondary, danger, small } from "./controls";

const has = (cls: string, re: RegExp) => cls.split(/\s+/).some((c) => re.test(c));

describe("control presets", () => {
  it("give inputs, selects and normal buttons the same height", () => {
    for (const p of [input, select, primary, secondary, danger]) expect(p.split(" ")).toContain("h-10");
    expect(small.split(" ")).toContain("h-8");
  });
  it("carry no outer margin", () => {
    for (const [name, p] of Object.entries(PRESETS)) expect(has(p, /^-?m[trblxy]?-/), name).toBe(false);
  });
  it("have a border on every button so bordered and borderless match", () => {
    for (const p of [primary, secondary, danger, small]) expect(p.split(" ")).toContain("border");
  });
  it("keep disabled buttons looking disabled", () => {
    for (const p of [primary, secondary, danger, small]) expect(p).toContain("disabled:opacity-50");
  });
});
```

Add one more test in the same file: `it("are never overridden by a class for the same property")`. It reads each `.tsx` under `src/` (outside tests), using `import.meta.glob("../**/*.tsx", { query: "?raw", eager: true })`. For every `` `${<preset>} <extra>` `` it fails if `<extra>` has a margin, text-colour, width, height or padding class that the preset already sets. The failure message lists `file: snippet`.

- [ ] **Step 2: Run it and see it fail**

Run: `cd frontend && npx vitest run src/components/controls.test.ts`
Expected: FAIL, "Cannot find module './controls'".

- [ ] **Step 3: Write `components/controls.ts`** with the presets above and `PRESETS = { input, select, textarea, primary, secondary, danger, small, smallDanger }`.

- [ ] **Step 4: Run the tests.** The preset tests pass. The override test fails and lists the known overrides. That list is the work list for Step 6.

- [ ] **Step 5: Write the failing Notify test** in `pages/Notify.test.tsx`. Use `mockFetch({"GET /api/notify": {status: 200, body: {wanted_pods: null}}})`, using the path that `newjob.notify()` actually calls. Assert:
  - `screen.getByLabelText("Pods wanted")` has class `h-10` and no `mb-3`;
  - `screen.getByRole("button", {name: "Notify me"})` has class `h-10`;
  - the input's label is not an ancestor of the button, and both sit in an element with class `items-end`.

- [ ] **Step 6: Move every page to the presets and remove each override.** Use these rules in every file:
  - the input sits under its label element, not inside a label with `text-sm`;
  - margins move to the layout (`gap`, or `mb-*` on a wrapper);
  - `${secondary} text-danger` becomes `danger`, and `${smallButton} text-danger` becomes `smallDanger`;
  - selects use `select`, including the one in `FilePicker.tsx`.

  Then open each route in `app/routes.tsx` in the browser in both themes and fix any row that still doesn't line up. Note each page you fixed for the PR description.

- [ ] **Step 7: Run everything.**
  Run: `cd frontend && npm run lint && npm run typecheck && npx vitest run && npm run build`
  Expected: everything passes, with no override failures left.

- [ ] **Step 8: Commit and open the PR.**
  `SLURM-<n>: add shared control styles and fix control alignment`. The PR body lists the fixed rows per page, with before and after screenshots of `/notify`.

## Task 2: Single-line panels and the icon top bar

SerenEdge: **SLURM-55** (part 2 of 3)

**Files:**
- Modify: `frontend/src/components/Panel.tsx`, `frontend/src/components/Panel.test.tsx`, `frontend/src/app/AppShell.tsx`, `frontend/src/app/ThemeToggle.tsx`, `frontend/src/pages/pages.test.tsx`
- Create: `frontend/src/components/icons.tsx`, `frontend/src/app/AppShell.test.tsx`
- KB: update `design-tokens-and-motifs`. The Panel motif becomes "a single 2px accent top line (`border-t-2 border-t-accent`)", and an Icons motif line names `icons.tsx` and `iconButton`.

**Interfaces:**
- Produces (`components/icons.tsx`): `SunIcon`, `MoonIcon`, `KeyIcon`, `SignOutIcon`. Each is `(props: { className?: string }) => JSX.Element`: a 24×24 `viewBox` SVG drawn with `fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"`, with `aria-hidden="true"` and a default class of `h-5 w-5`.
- Produces: `iconButton = "inline-flex h-8 w-8 items-center justify-center rounded-sm border border-border text-text-dim hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"`, exported from `icons.tsx`.
- `ThemeToggle()` keeps its signature. It renders `<button aria-label={label} title={label}>` with `label = next === "light" ? "Light theme" : "Dark theme"`, showing `SunIcon` when next is light and `MoonIcon` otherwise.

- [ ] **Step 1: Write the failing tests.**
  - **`Panel.test.tsx`:** the region has `border-t-2` and `border-t-accent`, and does not have `border-double` or `border-t-4`.
  - **`pages.test.tsx`, ThemeToggle:** `getByRole("button", {name: /theme/i})` contains an `svg`, its `title` equals its accessible name, and the name flips between "Light theme" and "Dark theme" on click.
  - **`AppShell.test.tsx`:** mock `GET /api/auth/me` with an account. Then:
    - `getByRole("link", {name: "Change password"})` has `href="/account/password"`, contains an `svg`, and has the class `focus-visible:outline`;
    - `getByRole("button", {name: "Sign out"})` contains an `svg`;
    - the account's full name is shown as text.

- [ ] **Step 2: Run them and see them fail.**
  Run: `cd frontend && npx vitest run src/components/Panel.test.tsx src/pages/pages.test.tsx src/app/AppShell.test.tsx`
  Expected: FAIL on `border-double` and on the missing svgs.

- [ ] **Step 3: Implement.**
  - **`Panel.tsx`:** replace `border-t-4 border-double border-t-accent` with `border-t-2 border-t-accent`.
  - **`icons.tsx`:** the four icons and `iconButton`.
  - **`ThemeToggle.tsx`:** the icon version described above.
  - **`AppShell.tsx`:** the header's right-hand group is `[ThemeToggle] [full name] [Change password icon link] [Sign out icon button]`. Use `aria-label` and `title` on the link and the button, with the icons inside, and `gap-2` between items.

- [ ] **Step 4: Run all frontend checks.**
  Run: `cd frontend && npm run lint && npm run typecheck && npx vitest run && npm run build`
  Expected: PASS.

- [ ] **Step 5: Check by eye** in both themes: the panels, and the top bar on the signed-in shell and on a signed-out page such as `/sign-in`.

- [ ] **Step 6: Update the KB entry**, then commit and open the PR. Commit message: `SLURM-<n>: single-line panels and icon top bar`.

## Task 3: The About page

SerenEdge: **SLURM-55** (part 3 of 3)

**Files:**
- Create: `frontend/src/pages/About.tsx`, `frontend/src/pages/About.test.tsx`
- Modify: `frontend/src/app/routes.tsx`, `frontend/src/api/client.ts`, `frontend/src/app/AppShell.tsx`, `frontend/src/pages/PublicPage.tsx`
- KB: add a `ui_system` entry "About page" linking `[[App shell, routing and API client]]` and `[[Design tokens and motifs]]`.

**Interfaces:**
- Consumes: `Panel`, `Wordmark` and `ThemeToggle` (the icon version from Task 2), and `getMe()` from `api/auth.ts`.
- Produces: `About(): JSX.Element` in `pages/About.tsx`. Add `"/about"` to `PUBLIC_PATHS` in `api/client.ts`, so a 401 on that page does not redirect. Add `["/about", () => <About />]` to `PUBLIC` in `routes.tsx`.

- [ ] **Step 1: Write the failing tests** in `pages/About.test.tsx`.

```tsx
it("stays on /about when signed out and offers Sign in", async () => {
  window.history.pushState({}, "", "/about");
  mockFetch({ "GET /api/auth/me": { status: 401, body: { error: "unauthenticated" } } });
  render(<App />);
  expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  expect(window.location.pathname).toBe("/about");
});
it("offers Back to dashboard when signed in", async () => { /* me → 200 */ });
it("names the creator, supervisor, repo and version", () => {
  // "Daham Dissanayake", link "@DahamDissanayake" → https://github.com/DahamDissanayake,
  // "Supervisor", link "@indrajithek" → https://github.com/indrajithek,
  // link to https://github.com/DahamDissanayake/slurm-deck/, text `v${pkg.version}`, "IIT research unit"
});
```

Also add tests that the signed-in top bar's `getByRole("link", {name: "About"})` has `href="/about"`, and that the `PublicPage` footer has an "About" link to `/about`.

- [ ] **Step 2: Run them and see them fail.**
  Run: `cd frontend && npx vitest run src/pages/About.test.tsx`
  Expected: FAIL, "Cannot find module './About'".

- [ ] **Step 3: Write `About.tsx`.**
  - **Frame:** `mx-auto max-w-3xl p-6`, with the wordmark and `ThemeToggle` at the top. The top link is "Back to dashboard" (to `/`) when `getMe()` resolves, and "Sign in" (to `/sign-in`) when it rejects.
  - **Panels, in order:**
    1. What Slurm Deck is
    2. How it started
    3. How it grew
    4. What it does today
    5. People
    6. Open source
  - **Footer:** `Slurm Deck · v{pkg.version} · MIT`.
  - **Copy:** use the facts in spec §Part 3 exactly. The timeline is May 2026 TUI; v1.0, 16 Jul 2026; v1.1, 25 Jul; v1.2, 25 Jul; v1.3, 26 Jul; v1.4, 28 Jul ("IIT GPU Manager" renamed to Slurm Deck); October 2026, the browser platform v2.0. The People panel has Daham Dissanayake (creator, @DahamDissanayake) and Supervisor, @indrajithek. Write it in plain words, as the rest of the UI is.
  - **Links:** external links use `rel="noreferrer"`.

- [ ] **Step 4: Wire it up.**
  - Add `"/about"` to `PUBLIC_PATHS` and to the `PUBLIC` routes.
  - In `AppShell.tsx`, add `<Link href="/about">About</Link>`, styled `text-sm text-text-dim hover:text-text`, before the theme icon.
  - In the `PublicPage` footer, add an `About` link next to `source`.

- [ ] **Step 5: Run all frontend checks.**
  Run: `cd frontend && npm run lint && npm run typecheck && npx vitest run && npm run build`
  Expected: PASS.

- [ ] **Step 6: Check by eye.** Open `/about` signed out and signed in, in both themes, and at 375px.

- [ ] **Step 7: Add the KB entry**, then commit and open the PR. Commit message: `SLURM-<n>: add the About page`.

## Order

All three tasks ship as one SerenEdge task, **SLURM-55**, in one PR, built in the order 1, 2, 3 with a commit after each. Task 3 relies on Task 2: it uses the icon `ThemeToggle` and edits the same top-bar markup.
