# CHANGELOG


## v1.1.0 (2026-07-18)

### Bug Fixes

- **artifacts**: Regenerate fixtures+ledger at v1.0.0 so HEAD replay verifies
  ([`2415bfe`](https://github.com/edycutjong/innkeeper/commit/2415bfe5cffc2f228d5d29c7a701cdeef6ae1fac))

Committed artifacts were generated at 0.1.0 while code ships 1.0.0; the version string is baked into
  pipeline_version/generator and cascades into Ed25519 signatures and sealed-PDF bytes, so a fresh
  clone of the previous HEAD failed 'innkeeper replay' with a signature mismatch. Also commits the
  deterministic report.md produced by the documented 'innkeeper report' beat.

- **assets**: Og-image chip LIVE→BUILT ON QWEN CLOUD (honest pre-deploy)
  ([`eb43b84`](https://github.com/edycutjong/innkeeper/commit/eb43b84cd235b897af1fe87b5c2cda26fcb371d7))

- **docs**: Correct GitHub handle in CI badge to edycutjong
  ([`b65b430`](https://github.com/edycutjong/innkeeper/commit/b65b430a0b0b53f526cf79dfb05825a595f9cf7a))

- **version**: Mcp handshake reports package __version__ instead of hardcoded 0.1.0
  ([`61de0ad`](https://github.com/edycutjong/innkeeper/commit/61de0ad77429b6a1ed5ce58b92ea0d9416c23ec0))

### Continuous Integration

- Add Stage 6 semantic-release to pipeline + versioning docs
  ([`6f14b08`](https://github.com/edycutjong/innkeeper/commit/6f14b08343b48da46a62ba13209892338e5f7337))

- Install live extra in quality stage (test_qwen_live needs openai)
  ([`1843a9c`](https://github.com/edycutjong/innkeeper/commit/1843a9c3810cf6937ff389ce9672b02f9bc43e6c))

### Features

- **site**: Wow landing page + 10-slide pitch deck + GitHub Pages deploy
  ([`f58405c`](https://github.com/edycutjong/innkeeper/commit/f58405c6bffa43addb6bd553e846560429432662))

- site/index.html: midnight grand-hotel landing (Fraunces/Manrope/JetBrains Mono, brass+emerald per
  _tokens.css) — animated hero, real-receipt count-ups (277/281 · 0 false clears · 404 tests · 100%
  cov), live-feel terminal replay of the real 2026-07-04 run, asymmetric feature grid with E[loss]
  gate math, 'Honest by design' mock disclosures, FAQ, art-deco motifs, WCAG AA,
  prefers-reduced-motion, full OG/Twitter metadata - site/pitch/index.html: 10-slide 1920x1080 deck
  (arrows/space/ESC-grid/P-notes/ C-contrast, 16in x 9in print verified 10 pages), doc-quality
  pipeline SVG, real seeded-night output, shipped-facts traction only - site assets: icon.svg,
  og-image.png, readme-hero.png, apple-touch-icon 180x180, CNAME innkeeper.edycu.dev -
  .github/workflows/pages.yml: Deploy Pages (configure-pages@v5 -> upload-pages-artifact@v3
  path:site -> deploy-pages@v4) - README: Live + Pitch Deck badges


## v1.0.0 (2026-07-14)

### Features

- Initial import of innkeeper-audit
  ([`26c51e0`](https://github.com/edycutjong/innkeeper/commit/26c51e0908c59ef185ac316c4cf232f782ac68ef))
