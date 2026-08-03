# Rubric: UX & Accessibility Judgment (CTL-0102, 0103, 0114)

Judgment review. Advisory. Owned by senior-uiux.
Covers what axe-core cannot — roughly two thirds of real WCAG failures.

## The keyboard-only pass — do this first, it takes 30 seconds
Unplug the mouse. Tab through the entire changed flow.

- [ ] Every interactive element is reachable
- [ ] Focus is always visible (and visible against its actual background)
- [ ] Tab order matches visual order
- [ ] Modal moves focus in on open, returns it to the trigger on close
- [ ] Escape closes anything dismissible
- [ ] Nothing traps focus permanently
- [ ] The whole task can be completed without a mouse

Any unchecked box is a finding and almost certainly a WCAG 2.1.1 or 2.4.3 failure.

## The three states
For every async view:
- [ ] **Loading** — is it visible within 100ms? Does it indicate progress or just spin?
- [ ] **Empty** — does it explain why it is empty and what to do?
- [ ] **Error** — what happened, why, what to do next, and a reference code if we cannot say

## Error message quality
Bad: "An error occurred." / "Invalid input." / "Something went wrong."
Good: "We could not save your changes because the file is larger than 10MB.
       Try a smaller file, or contact support with code E-4471."

For each error added: does it name the problem, the cause, and the next action?

## Copy
- [ ] Buttons are verbs describing what happens ("Delete 47 records", not "OK")
- [ ] No jargon the user has not been taught in this flow
- [ ] Destructive actions state the consequence and are not the default focus
- [ ] Nothing depends on colour alone to convey meaning

## Screen reader spot check
- [ ] Every image: informative → meaningful alt; decorative → `alt=""`
- [ ] Every icon-only control has an accessible name
- [ ] Heading levels form a sensible outline with no skips
- [ ] Dynamic updates announced via a live region
- [ ] Form fields have real `<label>` elements, not placeholders

## Zoom and small screens
- [ ] Usable at 200% browser zoom
- [ ] Usable at 320px width
- [ ] Tap targets at least 44×44px
