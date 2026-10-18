# Alternative design directions

Two complete alternative token sets for the Actron UI (spec C, C10). Both are dark only and keep the same token names, scale and components, so trying one means replacing the values in the `:root` block of `frontend/styles/tokens.css` (and, for fonts, the three `next/font` imports in `frontend/app/layout.tsx`). The state colours stay shared with Slack through `frontend/lib/states.json`; if a direction changes them, update that file too so the UI and Slack still agree. Contrast was checked for each set with the same rule as `frontend/tests/unit/contrast.test.ts` (text 4.5:1, large text and UI parts 3:1).

The built direction is "Evidence console" (`DESIGN.md`).

## A. Ink dossier

Warmer, quieter and more editorial: a case file read under a desk lamp. Serif-forward headlines, a softer highlighter, tighter chrome. Suits a team that reads the evidence more than it operates the pipeline.

```css
:root {
  --ink-0: #0d0c0a;
  --ink-1: #12110e;
  --ink-2: #181613;
  --ink-3: #1f1d19;
  --line-1: #24221d;
  --line-2: #312e28;
  --text-1: #ece6da;   /* 15.9:1 on ink-0 */
  --text-2: #b0a896;   /* 8.4:1 */
  --text-3: #8c8576;   /* 5.3:1 on ink-0, 4.6:1 on ink-3 */
  --text-disabled: #5f5a50;
  --accent: #f2d06b;   /* amber highlighter */
  --accent-ink: #0d0c0a;
  --accent-wash: rgb(242 208 107 / 0.14);
  --state-ok: #6fbf8e;
  --state-conflict: #e86a5c;
  --state-possible: #e3a35a;
  --state-running: #7ab3c9;
  --state-idle: #8c8576;
  --node-code: #cfc8ba;
  --node-github: #a79f90;
  --node-slack: #c0a9c9;
  --node-linear: #98aecb;
  --node-core: #ece6da;
}
```

- Type: display **Fraunces** (soft optical sizes, used at weight 400 for headlines and quotes), UI **Source Sans 3**, data **JetBrains Mono**.
- Shape: radius 2 / 4 / 6; hairlines only, no overlay shadow besides modals.
- Trade-off: lovely for reading quotes; the amber accent sits closer to the "possible conflict" amber, so `--state-possible` moves to a redder orange and chips must lean on their text labels.

## B. Signal console

Higher contrast and a stronger accent: a control room at night. Suits demos on projectors and teams that run many requests at once.

```css
:root {
  --ink-0: #050505;
  --ink-1: #0b0b0b;
  --ink-2: #111111;
  --ink-3: #181818;
  --line-1: #222222;
  --line-2: #333333;
  --text-1: #f5f5f5;   /* 19.3:1 on ink-0 */
  --text-2: #b8b8b8;   /* 10.4:1 */
  --text-3: #8f8f8f;   /* 6.3:1 on ink-0, 5.4:1 on ink-3 */
  --text-disabled: #606060;
  --accent: #c6ff3d;   /* stronger lime highlighter */
  --accent-ink: #050505;
  --accent-wash: rgb(198 255 61 / 0.16);
  --state-ok: #3fd68f;
  --state-conflict: #ff5c63;
  --state-possible: #ffad42;
  --state-running: #4cc9ff;
  --state-idle: #8f8f8f;
  --node-code: #d6dae0;
  --node-github: #a3afbd;
  --node-slack: #c4b1ea;
  --node-linear: #94bbf2;
  --node-core: #f5f5f5;
}
```

- Type: display **Newsreader** at weight 500, UI **IBM Plex Sans**, data **IBM Plex Mono** (one superfamily for UI and data).
- Shape: radius 4 / 6 / 10 as built; 2-px focus rings and 1.5-px chip borders.
- Trade-off: reads at a distance and on poor projectors; on a laptop at night the near-pure black and brighter text are harsher, and the lime accent is louder, so it must stay limited to the evidence path and the one primary action.
