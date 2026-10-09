# Accessibility checklist (WCAG 2.2 AA)

Go through this for every screen the change touched. An item that doesn't apply is skipped, not marked done.

## Checklist

**Labels and names**
- [ ] Every input has a visible `<label>` tied to it (`for`/`id` or wrapping). `aria-label` only when a visible label is impossible (e.g. a search field with an icon).
- [ ] Icon-only buttons have an accessible name (`aria-label` or visually hidden text).
- [ ] Buttons and links say what they do ("Delete invoice", not "Click here"); no empty links or buttons.

**Keyboard**
- [ ] Every interactive element is reachable with Tab and works with Enter/Space; custom widgets also with the keys their pattern expects (Escape closes, arrows move within menus, tabs and listboxes).
- [ ] Tab order follows the visual order; no `tabindex` above 0.
- [ ] No keyboard traps, except a modal, which keeps focus inside while open and returns it to the trigger on close.
- [ ] A skip-to-content link on pages with repeated navigation.

**Visible focus**
- [ ] Every focusable element shows a clear focus indicator. Never remove the outline without a replacement that meets contrast.
- [ ] Focus is not hidden behind sticky headers or overlays.

**Contrast and color**
- [ ] Text contrast at least 4.5:1, large text (24px, or 18.66px bold) at least 3:1.
- [ ] Icons, input borders and focus indicators at least 3:1 against what's next to them.
- [ ] Color is never the only signal: errors, required fields, status and links also use text, an icon or an underline.

**Target size**
- [ ] Pointer targets at least 24x24 CSS px (WCAG 2.2 AA), or spaced so a 24px circle around each doesn't overlap another; aim for 44x44 on touch screens.

**Semantics and landmarks**
- [ ] `<html lang>` set and a descriptive `<title>` per page.
- [ ] Landmarks: one `<main>`, `<nav>` (labelled when there's more than one), `<header>`, `<footer>`.
- [ ] One `<h1>`, headings in order without skipped levels.
- [ ] Native elements for their job: `<button>` for actions, `<a href>` for navigation, `<table>` with `<th scope>` for tabular data, lists as lists. No `div` with a click handler.

**Images and media**
- [ ] Informative images have `alt` that says what they convey; decorative ones `alt=""`.
- [ ] Charts and complex images have a text alternative (a summary or the data table).
- [ ] Video has captions; no audio or video autoplays with sound.

**Motion**
- [ ] Animations respect `prefers-reduced-motion`.
- [ ] Nothing flashes more than 3 times per second; moving content that lasts over 5 seconds can be paused.

**Forms and errors**
- [ ] Required fields marked in text, not only by color or an asterisk without explanation.
- [ ] Errors say what's wrong and how to fix it, sit next to the field and are tied to it (`aria-describedby`), with `aria-invalid` on the field.
- [ ] On submit with errors, focus moves to the first invalid field or to an error summary that links to the fields.
- [ ] Known fields use `autocomplete` (`email`, `name`, `current-password`, ...). The user's input is kept after an error.

**Live regions**
- [ ] Status updates that appear without a page load (saved, loading finished, results count) are announced with `role="status"` / `aria-live="polite"`.
- [ ] Urgent errors use `role="alert"`; use it sparingly.
- [ ] The live region exists in the DOM before the message is put in it.

**Zoom and reflow**
- [ ] At 200% zoom, and at 320px wide, content reflows without loss and without horizontal scrolling (except tables, maps and code).

## How to check

1. **Automated pass.** Use the accessibility tool the project already has (an axe integration in the e2e or component tests, a lint plugin such as `eslint-plugin-jsx-a11y`, Lighthouse in CI). If none is installed, run axe in the browser session against the changed screens when you can do so without adding a dependency; otherwise tell the user and offer to add it. Fix every violation on the changed screens or report it with the reason.
2. **Keyboard pass.** Without the mouse, Tab through the changed screen from the top: every control reachable, focus always visible and in a sensible order, each action doable with Enter/Space/Escape, dialogs trap and return focus.
3. **Accessibility tree.** In the browser's accessibility view, check that controls have the names you expect and headings and landmarks form the outline.
4. **Contrast.** Check new color pairs with the browser's contrast checker or the automated pass; for tokens, check the pair once and reuse it.

Automated tools find roughly a third of the problems. The keyboard pass and this checklist cover the rest that can be checked without a screen reader; say in the publish gate summary that no screen reader test was done, if none was.
