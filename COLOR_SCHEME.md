# Color scheme

Source of truth for the app's color tokens (`tailwind-src/input.css`'s
`@theme` block + `.dark` override, and their hand-matched duplicates in
`static/css/editor.css`, which isn't run through Tailwind). Update this
file whenever the palette changes — it's the record of what's active and
what it replaced, not a design brief.

## Active palette

Given as five ready-made ramps (Onyx / Brick Ember / Dim Grey / Ash Grey
/ Ghost White); each is used verbatim as one of the app's five named
color roles.

| Ramp name (as given) | App role | 500 | Used for |
|---|---|---|---|
| Onyx | `brand` | `#669966` | Primary actions, links, focus rings — the most load-bearing color in the app |
| Brick Ember | `bell` | `#fe011b` | Secondary accent — tertiary chart series, hover tints where `brand` would be too loud |
| Ghost White | `navy` | `#68609f` | Accent only — sidebar/auth chrome, `badge-purple` |
| Dim Grey | `twilight` | `#7a8185` | Sidebar/auth surface color (`.twilight-surface`, solid); source for the dark-mode neutral scale below |
| Ash Grey | `mist` | `#6c9390` | Light airy tints — callouts, info surfaces, auth-screen glow |

**This mapping was revised once** (see History → "First attempt" below)
after the app still looked like the previous palette post-deploy. The
root cause: `brand` had been assigned to "whichever given color is most
saturated" for three palette swaps running (Amaranth → Flag Red → Brick
Ember), and `twilight` (which governs most of the app's actual surface
area, via the dark-mode neutral scale) had been assigned to "whichever
given color is hue-closest to the app's original blue-violet" for most
of them too — both rules kept converging on similar results regardless
of the input palette, so the page kept reading as barely-changed even
though the hex values were genuinely different each time. This revision
breaks both rules on purpose: `brand` goes to Onyx, the one hue in this
palette that isn't a shade of red or grey (a real color shift, not just
a different red); `twilight` goes to Dim Grey, which is near-truly-
achromatic rather than carrying Ghost White's residual blue-violet cast
into most of the app's surface area. Brick Ember (the palette's one
saturated red) still gets used somewhere visible (`bell`) rather than
being wasted — just not in the role most responsible for the page's
overall first impression.

### Full ramps

```
--color-brand-50:  #f0f5f0;   --color-bell-50:  #ffe6e8;
--color-brand-100: #e0ebe0;   --color-bell-100: #ffccd1;
--color-brand-200: #c2d6c2;   --color-bell-200: #fe9aa4;
--color-brand-300: #a3c2a3;   --color-bell-300: #fe6776;
--color-brand-400: #85ad85;   --color-bell-400: #fe3448;
--color-brand-500: #669966;   --color-bell-500: #fe011b;
--color-brand-600: #527a52;   --color-bell-600: #cb0115;
--color-brand-700: #3d5c3d;   --color-bell-700: #980110;
--color-brand-800: #293d29;   --color-bell-800: #65010b;
--color-brand-900: #141f14;   --color-bell-900: #330005;
--color-brand-950: #0e150e;   --color-bell-950: #240004;

--color-navy-50:  #f0eff5;    --color-twilight-50:  #f2f2f3;    --color-mist-50:  #f0f4f4;
--color-navy-100: #e1dfec;    --color-twilight-100: #e4e6e7;    --color-mist-100: #e2e9e9;
--color-navy-200: #c3bfd9;    --color-twilight-200: #cacdce;    --color-mist-200: #c4d4d3;
--color-navy-300: #a49fc6;    --color-twilight-300: #afb3b6;    --color-mist-300: #a7bebc;
--color-navy-400: #8680b3;    --color-twilight-400: #959a9d;    --color-mist-400: #8aa8a6;
--color-navy-500: #68609f;    --color-twilight-500: #7a8185;    --color-mist-500: #6c9390;
--color-navy-600: #534d80;    --color-twilight-600: #62676a;    --color-mist-600: #577573;
--color-navy-700: #3e3960;    --color-twilight-700: #494d50;    --color-mist-700: #415856;
--color-navy-800: #2a2640;    --color-twilight-800: #313435;    --color-mist-800: #2b3b3a;
--color-navy-900: #151320;    --color-twilight-900: #181a1b;    --color-mist-900: #161d1d;
--color-navy-950: #0f0d16;    --color-twilight-950: #111213;    --color-mist-950: #0f1514;
```

### Dark-mode neutral scale

`.dark`'s `--color-slate-*` override reuses Twilight's own ramp read back
to front (light-mode "50" = lightest surface → dark-mode's darkest;
"900" = darkest text → dark-mode's lightest), rather than a separately
desaturated scale — Twilight (Dim Grey) is already muted enough (~4%
saturation) to work directly, and reads as true neutral grey rather than
carrying a blue-violet cast into most of the app's surface area:

```
--color-slate-50:  #111213;   (twilight-950)
--color-slate-100: #181a1b;   (twilight-900)
--color-slate-200: #313435;   (twilight-800)
--color-slate-300: #494d50;   (twilight-700)
--color-slate-400: #62676a;   (twilight-600)
--color-slate-500: #7a8185;   (twilight-500)
--color-slate-600: #959a9d;   (twilight-400)
--color-slate-700: #afb3b6;   (twilight-300)
--color-slate-800: #cacdce;   (twilight-200)
--color-slate-900: #f2f2f3;   (twilight-50)
```

### Sidebar / auth surface

`.twilight-surface` — solid `twilight-950` (`#111213`), applied to the
sidebar, its mobile top bar, and the login/MFA/password-reset screens.

## History

### First attempt: same five ramps, wrong role mapping

The initial pass at this same Onyx/Brick Ember/Dim Grey/Ash Grey/Ghost
White palette used the "most saturated → brand" / "hue-closest-to-
original → twilight" rules that had produced the app's palette every
time before this one:

| Ramp name (as given) | App role | 500 |
|---|---|---|
| Brick Ember | `brand` | `#fe011b` |
| Dim Grey | `bell` | `#7a8185` |
| Onyx | `navy` | `#669966` |
| Ghost White | `twilight` | `#68609f` |
| Ash Grey | `mist` | `#6c9390` |

Deployed, verified live (fresh CSS hash, correct hex present in the
served file) — but reported as "still looks like the old one" after a
hard refresh. Superseded by the mapping above rather than kept as a
separate numbered palette, since it's the same five source colors, just
assigned to different roles.

### Previous: Space Indigo / Lavender Grey / Platinum / Punch Red / Flag Red

Given as five ready-made ramps, mapped by hue/saturation the same way as
the active palette above.

| Ramp name (as given) | App role | 500 |
|---|---|---|
| Flag Red | `brand` | `#fa052e` |
| Punch Red | `bell` | `#ed122b` |
| Lavender Grey | `navy` | `#6a7a95` |
| Space Indigo | `twilight` | `#65699a` |
| Platinum | `mist` | `#618d9e` |

```
--color-brand-50: #fee6ea;    --color-navy-50: #f0f2f4;     --color-twilight-50: #f0f0f5;
--color-brand-100: #fecdd5;   --color-navy-100: #e1e4ea;    --color-twilight-100: #e0e1eb;
--color-brand-200: #fd9bab;   --color-navy-200: #c3cad5;    --color-twilight-200: #c1c3d7;
--color-brand-300: #fc6982;   --color-navy-300: #a5afc0;    --color-twilight-300: #a2a5c3;
--color-brand-400: #fb3758;   --color-navy-400: #8894aa;    --color-twilight-400: #8487ae;
--color-brand-500: #fa052e;   --color-navy-500: #6a7a95;    --color-twilight-500: #65699a;
--color-brand-600: #c80425;   --color-navy-600: #556177;    --color-twilight-600: #51547b;
--color-brand-700: #96031c;   --color-navy-700: #3f495a;    --color-twilight-700: #3c3f5d;
--color-brand-800: #640212;   --color-navy-800: #2a313c;    --color-twilight-800: #282a3e;
--color-brand-900: #320109;   --color-navy-900: #15181e;    --color-twilight-900: #14151f;
--color-brand-950: #230106;   --color-navy-950: #0f1115;    --color-twilight-950: #0e0f16;

--color-mist-50: #eff4f5;     --color-bell-50: #fde7ea;
--color-mist-100: #dfe8ec;    --color-bell-100: #fbd0d5;
--color-mist-200: #c0d1d8;    --color-bell-200: #f8a0aa;
--color-mist-300: #a0bac5;    --color-bell-300: #f47180;
--color-mist-400: #81a4b1;    --color-bell-400: #f14156;
--color-mist-500: #618d9e;    --color-bell-500: #ed122b;
--color-mist-600: #4e717e;    --color-bell-600: #be0e23;
--color-mist-700: #3a545f;    --color-bell-700: #8e0b1a;
--color-mist-800: #27383f;    --color-bell-800: #5f0711;
--color-mist-900: #131c20;    --color-bell-900: #2f0409;
--color-mist-950: #0e1416;    --color-bell-950: #210206;
```

Dark-mode neutral scale (Space Indigo's own ramp, reversed):

```
--color-slate-50: #0e0f16;   --color-slate-600: #8487ae;
--color-slate-100: #14151f;  --color-slate-700: #a2a5c3;
--color-slate-200: #282a3e;  --color-slate-800: #c1c3d7;
--color-slate-300: #3c3f5d;  --color-slate-900: #f0f0f5;
--color-slate-400: #51547b;
--color-slate-500: #65699a;
```

Sidebar/auth surface was solid `twilight-950` (`#0e0f16`) here too — this
palette is also where the sidebar/auth gradient was changed to a flat
color, by request.

### Before that: Brown Red / Amaranth / Taupe Grey / Rosy Granite / Night Bordeaux

Given as five single hex values (not full ramps), each treated as the
anchor of a generated 50–950 ramp (lightness curve
95/90/80/70/60/50/40/30/20/10/7%, hue/saturation held from the source
color, exact given hex slotted in at its own natural lightness step).

| Given color | Hex | App role | Ramp step it anchored |
|---|---|---|---|
| Amaranth | `#db324d` | `brand` | 500 |
| Night Bordeaux | `#511c29` | `navy` | 800 |
| Taupe Grey | `#56494e` | `twilight` | 700 |
| Rosy Granite | `#a29c9b` | `mist` | 400 |
| Brown Red | `#a62639` | `bell` | 600 |

Dark-mode neutral scale was a separately hand-desaturated ramp on
Taupe Grey's hue (~337°), not a direct reuse of the Twilight ramp itself
(that color's own saturation didn't drop low enough at every step to
double as body text at large sizes without a bit more desaturation).

### Original: "Persian Blue" client-supplied palette

The palette this app shipped with — five named ramps, all in a blue/
violet-blue hue family (`brand` H≈234°, `navy` H≈248°, `twilight` H≈240°,
`mist` H≈198°, `bell` H≈202°). `.twilight-surface` was a `brand-700 →
navy-800 → twilight-950` gradient (this is the one both later palettes'
gradient/solid history refers back to).

```
--color-brand-50: #e8eafc;    --color-navy-50: #eae7fe;    --color-twilight-50: #e9e9fb;
--color-brand-100: #d2d6f9;   --color-navy-100: #d4cefd;   --color-twilight-100: #d3d3f8;
--color-brand-200: #a5adf3;   --color-navy-200: #aa9dfb;   --color-twilight-200: #a8a8f0;
--color-brand-300: #7883ed;   --color-navy-300: #7f6cf9;   --color-twilight-300: #7c7ce9;
--color-brand-400: #4a5ae8;   --color-navy-400: #543bf7;   --color-twilight-400: #5151e1;
--color-brand-500: #1d31e2;   --color-navy-500: #290af5;   --color-twilight-500: #2525da;
--color-brand-600: #1727b5;   --color-navy-600: #2108c4;   --color-twilight-600: #1e1eae;
--color-brand-700: #121d87;   --color-navy-700: #190693;   --color-twilight-700: #161683;
--color-brand-800: #0c145a;   --color-navy-800: #110462;   --color-twilight-800: #0f0f57;
--color-brand-900: #060a2d;   --color-navy-900: #080231;   --color-twilight-900: #07072c;
--color-brand-950: #040720;   --color-navy-950: #060122;   --color-twilight-950: #05051f;

--color-mist-50: #eaf5fa;     --color-bell-50: #eaf4fa;
--color-mist-100: #d5ecf6;    --color-bell-100: #d6eaf5;
--color-mist-200: #acd9ec;    --color-bell-200: #add4eb;
--color-mist-300: #82c6e3;    --color-bell-300: #84bfe1;
--color-mist-400: #59b3d9;    --color-bell-400: #5baad7;
--color-mist-500: #2fa0d0;    --color-bell-500: #3294cd;
--color-mist-600: #2680a6;    --color-bell-600: #2877a4;
--color-mist-700: #1c607d;    --color-bell-700: #1e597b;
--color-mist-800: #134053;    --color-bell-800: #143b52;
--color-mist-900: #09202a;    --color-bell-900: #0a1e29;
--color-mist-950: #07161d;    --color-bell-950: #07151d;
```

Original dark-mode neutral scale (hand-desaturated from Twilight's own
blue-violet hue):

```
--color-slate-50: #14152b;   --color-slate-600: #a6a9c2;
--color-slate-100: #1c1e3a;  --color-slate-700: #c1c3d6;
--color-slate-200: #2a2d4d;  --color-slate-800: #dcddea;
--color-slate-300: #3a3e63;  --color-slate-900: #f2f2f8;
--color-slate-400: #6b6f8f;
--color-slate-500: #8b8fab;
```
