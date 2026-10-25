# UI polish: control alignment, single-line panels, icon top bar and About page

Date: 2026-10-25 · Requested by: Daham Dissanayake (Project Head)

## Why

The Head previewed the web platform locally on 2026-10-25 and found three
things to fix before cutover:

1. **Controls don't line up.** On `/notify`, the "Pods wanted" box sits higher
   than the "Notify me" button beside it, so the button's bottom edge is below
   the box's.
2. **The double line on top of every section** (the TUI's double-ruled top
   edge on `Panel`) should be a single line.
3. **There is no About page.** Slurm Deck is open source and should say what
   it is, how it started and who made it, to anyone who wants to know.

The Head also wants the top bar's text actions turned into designed icon
buttons.

## Goals

- Every text box, select and button in a row lines up, on every page, in both
  themes.
- Every `Panel` has a single accent line on top in place of the double rule.
- The top bar has an **About** item, and theme, Change password and Sign out
  are icon buttons.
- A public About page, readable signed in or signed out.

## Non-goals

- No new colours, fonts or layout changes beyond what is listed here.
- No icon library or other new dependency. Icons are inline SVG in our own
  code (convention: no new dependencies without asking).
- No backend changes. The About page is static frontend content.
- No redesign of the sidebar or the page contents beyond alignment fixes.

## Anti-goals (failure even if it "works")

- Icon buttons that screen readers or tests can't identify. Every icon button
  keeps an accessible name equal to the old text.
- Fixing `/notify` alone while the same kind of bug stays elsewhere.
- An About page that only works for signed-in users, or whose history
  disagrees with the repo.

## Part 1: One set of control styles, and an alignment pass

**Root cause found during design.** `Notify.tsx` builds the pods box from the
shared preset `field` (`mt-1 mb-3 ...`) and appends `mb-0` to cancel the
margin. Tailwind resolves two classes for the same property by their order in
the generated stylesheet, not by their order in `className`. `mb-3` comes
after `mb-0` there, so the 12px bottom margin stays. The row is
`flex items-end`, so it aligns the label's bottom with the button's bottom,
and the input ends up 12px higher. The heights also differ:

- the input inherits `text-sm` from its label;
- the primary button has no border;
- the secondary button has a 1px border.

The same "preset plus an override for the same property" pattern appears in
about eight other places:

- `Notify.tsx` and `NewJob/StepReview.tsx`: `${field} mb-0`
- `Files.tsx`: `${secondary} text-danger`
- `admin/UserDetail.tsx`: `${smallButton} text-danger` (twice)
- `admin/Users.tsx`, `Environments.tsx`, `UploadPanel.tsx`, `NewJob/StepInputs.tsx`: margin and layout additions

Some of these may be failing quietly too, such as a Delete button that isn't
red.

The control styles also exist as four separate copies that drift apart:

- `PublicPage.tsx`: `Field` and `button`
- `admin/AdminLayout.tsx`: `inputClass`, `smallButton`, `primaryButton`
- `NewJob/StepInputs.tsx`: `field`, `primary`, `secondary`
- `components/buttons.ts`: `smallButton`

**What gets built:**

- **One module for control styles.** It lives in
  `frontend/src/components/controls.ts`, the builder's call, extending
  `buttons.ts` or replacing it.
  - It defines named presets for text input, select, textarea, primary
    button, secondary button, danger button and small button. Full width is
    a separate opt-in, not baked into the input preset.
  - Inputs, selects and normal-size buttons share one fixed height (`h-10`,
    the builder's call), with matching font size and border width. A
    borderless primary button still matches a bordered one, for example with
    a transparent border.
  - Small buttons have their own smaller fixed height, and small inputs, if
    any, match it.
  - Presets carry no outer margin. Spacing comes from the layout (`gap`, or a
    wrapping element).
- **Every page and component uses these presets.** The four old copies are
  removed or re-exported from the new module.
- **No more overriding a preset with a class for the same property.** A
  variant becomes a named preset, such as `danger`, rather than
  `${secondary} text-danger`. Adding classes for unrelated properties, like
  `ml-auto` or `whitespace-nowrap`, is still fine.
- **Labelled inputs in a row with a button.** The button lines up with the
  input itself, not the label. Either the label sits above in its own
  element, or the row uses `items-end` on controls of equal height with no
  margins.
- **The pass.** Go through every route in `app/routes.tsx` and every
  component that shows controls, in light and dark themes, and fix each row
  that doesn't line up. The builder lists in the pull request what was fixed
  on each page.
- **Tests:**
  - a unit test checks that the presets give inputs, selects and buttons the
    same height class and no margin classes;
  - a Notify page test checks that the pods input and the Notify me button
    carry the shared height preset;
  - a test, or a simple lint check in the test suite, fails when a known
    preset is combined with a class for the same property (margin, colour,
    width). Whether it is a test or a script is the builder's call.

## Part 2: Single-line panels and the icon top bar

**Panel.** In `components/Panel.tsx`, `border-t-4 border-double border-t-accent`
becomes a single accent line, `border-t-2 border-t-accent` (thickness is the
builder's call, 2px suggested). The rest of the panel is unchanged. Update
`Panel.test.tsx` and the KB entry *Design tokens and motifs*, whose motif
text describes the double rule.

**Top bar (`app/AppShell.tsx`).** Left to right:

- the wordmark;
- the `#cluster-status` slot;
- on the right: **About** (text link to `/about`), the theme icon button, the
  account's full name as text, the Change password icon button (to
  `/account/password`) and the Sign out icon button.

Icon buttons:

- **Theme:** a sun when dark is active (it switches to light), a moon when
  light is active.
- **Change password:** a key.
- **Sign out:** an exit or log-out arrow.
- Each has `aria-label` and `title` equal to the old text: "Light theme" or
  "Dark theme", "Change password", "Sign out". Screen readers, the tooltip
  and tests all find it by that name.
- They are square, the same size as each other and the small control height
  from Part 1, with a visible keyboard focus ring and hover in the accent
  colour.
- They are drawn with inline SVG using `currentColor`, so they follow the
  theme tokens. They live in one small icons module,
  `frontend/src/components/icons.tsx`, the builder's call.

`ThemeToggle` is used on the signed-out pages too, so those get the icon
version as well.

## Part 3: The About page

**Route:** `/about`, a public route. It renders without `AppShell`, so it
works signed out and never redirects to sign-in.

**Frame:** wider than the sign-in card (`max-w-3xl`, the builder's call). It
has the wordmark, the theme icon button and one link back:

- "Sign in" when signed out;
- "Back to dashboard" when signed in.

My call: decide which to show by trying `getMe()` without triggering the 401
redirect. If that is awkward, always show both links. The builder decides.

**Links to it:**

- the **About** item in the signed-in top bar (Part 2);
- an "About" link in the `PublicPage` footer, next to "source".

**Content.** Static, written in the page component, using `Panel` sections.
The text below is the agreed outline. The builder writes the final wording in
the project's plain style.

1. **What Slurm Deck is.** An open-source platform for sharing GPU machines
   between researchers. People schedule jobs, manage files and datasets, and
   open notebook sessions from a browser. It is built to make everyday MLOps
   work on shared hardware easier.
2. **How it started.** It began at the **IIT research unit**, which had a
   single GPU machine and several researchers who all needed to run models
   on it. There was no fair way to share it or queue work. The project
   started as a way to manage that one machine's resources and schedule
   everyone's tasks with Slurm. It grew one requirement at a time into the
   version running today.
3. **How it grew.** A timeline, with dates taken from the repo's tags and
   history:
   - **May 2026:** the first build, an SSH terminal (TUI) app on Slurm.
   - **v1.0, 16 Jul 2026:** baseline release.
   - **v1.1, 25 Jul 2026:** one access model for shared storage, notebook
     isolation and session audit.
   - **v1.2, 25 Jul 2026:** launch flow redesign.
   - **v1.3, 26 Jul 2026:** TUI design unification.
   - **v1.4, 28 Jul 2026:** renamed from "IIT GPU Manager" to Slurm Deck.
   - **October 2026:** work starts on the browser platform (v2.0), which
     replaces the SSH TUI. It covers jobs, uploads, notebooks, environments,
     usage and admin, each shaped by what the researchers needed.
4. **What it does today.** A short feature list matching the sidebar: jobs,
   files and uploads, environments, models, services and notebooks, usage,
   notifications, and admin.
5. **People.**
   - **Daham Dissanayake**, creator, [@DahamDissanayake](https://github.com/DahamDissanayake)
   - **Supervisor**, [@indrajithek](https://github.com/indrajithek). The
     GitHub handle is shown; a full name only if the Head supplies one.
6. **Open source.** MIT licence. Source at
   https://github.com/DahamDissanayake/slurm-deck/. Other sites can run it on
   their own hardware. Contributions go through the repo.
7. **Footer:** `Slurm Deck · v{package version} · MIT`.

**Site neutrality.** This page is about the project's own history, so naming
IIT is content, not site configuration. The convention against hardcoding
site details is about hostnames, IPs and similar settings. Nothing on the page
depends on the site running it.

**Tests:**

- `/about` renders signed out with no API call that redirects;
- the page shows the creator, the supervisor handle, the repo link and the
  version;
- the top bar's About link goes to `/about`;
- the `PublicPage` footer has an About link.

## Constraints

- No new dependencies. Inline SVG only.
- Colour tokens only (`design-tokens-and-motifs`), in both themes, with dark
  as the default.
- Frontend CI must pass: lint, typecheck, Vitest, build (`serenedge ci`).
- Accessible names are kept, so existing tests that find "Sign out",
  "Change password" or the theme toggle by name keep working.
- Each part is its own pull request under 800 changed lines.

## Left to the builder

- Exact height, border and focus-ring values, within the rules above.
- The name of the controls module, and whether `buttons.ts` is folded into it.
- The icon shapes, kept simple and the same stroke width.
- The final wording of the About copy, keeping the agreed facts.
- How the About page tells signed-in from signed-out visitors.

## Calls made in design (the Head can override)

- About is a text link, not an icon. The other three top-bar actions are
  icons.
- The full name stays as text in the top bar.
- Signed-out pages get the theme icon and an About footer link.
- A 2px single accent line, applied to every Panel.
- @indrajithek is shown by handle only, with no full name.
