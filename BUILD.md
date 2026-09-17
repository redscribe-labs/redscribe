# Frontend asset builds

Two self-hosted, committed static assets are built from source via npm —
Node/npm are **not** a runtime dependency of the deployed app (not used in
the Docker image at all), only a dev-time tool for whoever next touches the
editor JS or Tailwind classes.

## Tiptap editor bundle

`editor-src/main.js` is bundled by esbuild into `static/vendor/redscribe-editor.bundle.js`.

```
npm install
npm run build:editor
```

## Password strength meter

`strength-src/main.js` (zxcvbn-ts) is bundled by esbuild into
`static/vendor/redscribe-password-strength.bundle.js` — client-side,
advisory-only feedback shown under any password-creation field. The actual
policy is enforced server-side by `AUTH_PASSWORD_VALIDATORS`.

```
npm install
npm run build:strength
```

## Tailwind CSS

`tailwind-src/input.css` (theme tokens + component classes) is compiled by
the Tailwind CLI into `static/css/tailwind.css`, scanning all templates for
utility class usage automatically. Keep the Tailwind *source* file out of
`static/` — WhiteNoise's collectstatic post-processing tries to parse every
file under `static/` as a real asset and chokes on Tailwind's `@import
"tailwindcss";` directive if it ends up there.

```
npm install
npm run build:css
```

## Both

```
npm install
npm run build
```

Then commit the updated files in `static/vendor/` and `static/css/`.
