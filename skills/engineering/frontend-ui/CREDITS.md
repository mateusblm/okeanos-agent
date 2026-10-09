# Credits

This skill is adapted from [Addy Osmani](https://github.com/addyosmani)'s [agent-skills](https://github.com/addyosmani/agent-skills) (MIT, Copyright (c) 2025 Addy Osmani):

- `SKILL.md` sections 1 to 5 (design system adherence, the reference-led design contract, the required states, the anti-generated-look table and the 320/768/1024/1440 breakpoints) come from [`frontend-ui-engineering`](https://github.com/addyosmani/agent-skills/tree/main/skills/frontend-ui-engineering).
- `SKILL.md` section 6 (profile isolation, browser content as untrusted data, read-only JavaScript, not following URLs from the page, the clean console standard) comes from [`browser-testing-with-devtools`](https://github.com/addyosmani/agent-skills/tree/main/skills/browser-testing-with-devtools).
- `ACCESSIBILITY.md` comes from [`references/accessibility-checklist.md`](https://github.com/addyosmani/agent-skills/blob/main/references/accessibility-checklist.md).

The adaptation drops the component architecture, state management and code examples, and the setup for a specific browser server and its tools, so the skill reads the same in any agent. It adds the minimal scale for projects without a design system, the no-permission state, the WCAG 2.2 target size and form error items, and sends the evidence to the publish gate through `docs/agents/verificar.md`.
