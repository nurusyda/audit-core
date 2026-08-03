# Rubric: Frontend Judgment (CTL-0113)

Judgment review. Advisory. Owned by senior-frontend.

## Third-party scripts
For each one added:
- [ ] Async or deferred — never render-blocking
- [ ] What breaks if it fails to load? (Answer must not be "the page")
- [ ] What data does it receive? Is that in the privacy inventory?
- [ ] Size, measured
- [ ] Subresource integrity where the CDN supports it

Their outage becomes your outage. Their latency becomes your latency.

## Bundle regression triage
When CTL-0110 fires, report the CAUSE, not just the number:
- Which import grew it? (`source-map-explorer` or the bundler's analyser)
- Full library imported for one function?
- Barrel file pulling in an unrelated tree?
- Is it code-splittable? Should it be lazy?

## Rendering
- [ ] Route-level code splitting present
- [ ] Images have dimensions and `loading="lazy"` below the fold
- [ ] Fonts use `font-display: swap`
- [ ] Long lists virtualised
- [ ] No layout-triggering work inside a scroll or resize handler
