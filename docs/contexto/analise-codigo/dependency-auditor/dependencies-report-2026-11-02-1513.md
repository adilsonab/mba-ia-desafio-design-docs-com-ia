# Dependency Audit Report

- Project: `order-management-api` (version 1.0.0, private)
- Audit date: 2026-11-02
- Scope: entire project root
- Excluded: `node_modules`, `dist`, `.git`, `docs`
- Mode: analysis and reporting only. No project file was modified.

---

## 1. Summary

`order-management-api` is a REST API for order management, written in TypeScript and running on Node.js as an ES module. It uses Express 4 for HTTP, Prisma 5 with MySQL 8.0 for the ORM and database, Zod 3 for validation, jsonwebtoken and bcrypt for authentication, and Pino for logging. Tests run on Vitest 2 and Supertest.

**Ecosystems detected**

| Ecosystem | Manifest / Lockfile | Notes |
|-----------|---------------------|-------|
| npm (Node.js) | `package.json`, `package-lock.json` (lockfileVersion 3) | The only package-manager ecosystem. Versions are pinned exactly, with no `^` or `~`. The lockfile is present, so builds are reproducible. |
| Prisma schema | `prisma/schema.prisma`, `prisma/migrations/migration_lock.toml` | `prisma-client-js` generator, `mysql` provider |
| Docker | `docker-compose.yml` | `mysql:8.0` image, which is infrastructure rather than a package dependency. It is noted for context only. |
| Runtime | `package.json` `engines.node: ">=20"` | The local environment runs Node v20.19.5 and npm 11.17.0. |

**Direct dependency inventory:** 8 production dependencies and 17 development dependencies, 25 in total.

**Key findings**

- `npm audit`, run against the committed lockfile, reports 38 vulnerable packages: 4 critical, 12 high and 22 moderate. Five of the affected packages are direct dependencies: `express`, `vitest`, `zod`, `uuid` and `tsx`. The ESLint toolchain is flagged through the transitive `minimatch`.
- In production, the most significant exposure comes through `express@4.21.1`. Its transitive packages `path-to-regexp@0.1.10`, `body-parser@1.20.3`, `qs@6.13.0` and `proxy-addr` carry these advisories:
  - CVE-2024-52798 and CVE-2026-4867 (ReDoS)
  - CVE-2026-111181 (body-parser DoS)
  - CVE-2025-15284 and CVE-2026-82417 (qs DoS)
  - CVE-2026-90711 (proxy-addr IP spoofing)

  All of them are fixed within the 4.x line in `express@4.22.3`.
- `zod@3.23.8` is affected by CVE-2023-54404 (memory exhaustion, High). The fix exists only in `zod@4.6.6` and later, so there is no patched 3.x release. Remediation requires a major-version migration.
- `vitest@2.1.4` is affected by these advisories:
  - CVE-2025-24964 (RCE while the API server is listening, Critical)
  - CVE-2026-47429 (Critical)
  - transitive `tinypool` CVE-2026-104848 and CVE-2026-104849 (Critical)
  - transitive `vite` and `esbuild` advisories

  The exposure is limited to development and CI.
- `bcrypt@5.1.1` was last released on 2023-08-16, more than 3 years ago. Its 5.x line brings in `@mapbox/node-pre-gyp@1.0.11`, which in turn uses deprecated `tar@6.2.1`. That `tar` version carries several Critical and High path-traversal CVEs, including CVE-2026-24842, CVE-2026-23745 and CVE-2026-73566. These are exercised at install time.
- These packages are end of life or legacy:
  - `eslint@8.57.1`: end of life since 2024-10-05. ESLint 9 is also end of life as of 2026-08-06.
  - `@prisma/client` and `prisma@5.22.0`: the 5.x line has had no release since 2024-11-05, and the current stable release is 7.10.1.
  - The Node.js 20 runtime, which the `engines` field allows and the local environment uses, reached end of life on 2026-04-30.
- `supertest@7.0.0` is marked deprecated in the registry metadata ("Please upgrade to supertest v7.1.3+").
- `@types/uuid@10.0.0` is unnecessary. `uuid` 11 and later ship their own types, and the `@types/uuid` package itself is now a deprecated stub.
- `pino-http@10.3.0` is declared as a production dependency but is never imported anywhere in `src`, `tests` or `prisma`, so it is dead weight.
- All licenses are permissive (MIT, Apache-2.0, BSD-2-Clause), so no copyleft or legal risk was identified.

**Validation sources and limitations**

- The Context7 and Firecrawl MCP servers were not available in this session.
- Versions were validated live against the official npm registry using `npm view` for latest versions, dist-tags, release times and deprecation flags.
- Vulnerabilities were validated with `npm audit` against the committed `package-lock.json`. The command ran on a scratch copy of the lockfile, not in the project. GHSA-to-CVE mapping used the GitHub Advisory Database REST API (`api.github.com/advisories`).
- Lifecycle data came from these official pages:
  - `expressjs.com/en/support`
  - `eslint.org/version-support`
  - the Node.js release schedule (`github.com/nodejs/Release`)
- `npm view prisma version` returns `8.0.0-rc.29` because the `latest` dist-tag currently points at a release candidate. This report treats `7.10.1`, the `prev` dist-tag and the newest non-prerelease, as the latest stable version.

---

## 2. Critical Issues

### 2.1 Security vulnerabilities (direct dependencies and their production-relevant transitives)

| # | Direct dependency | Affected package (resolved) | CVE / Advisory | Severity (GHSA) | Fixed in | Exposure |
|---|-------------------|-----------------------------|----------------|-----------------|----------|----------|
| 1 | express 4.21.1 | path-to-regexp 0.1.10 | CVE-2024-52798 (GHSA-rhx6-c78j-4q9w), ReDoS | High | path-to-regexp 0.1.12, through express 4.22.3 | Production, at the HTTP routing layer |
| 2 | express 4.21.1 | path-to-regexp 0.1.10 | CVE-2026-4867 (GHSA-37ch-88jc-xwx2), ReDoS through multiple route parameters | High | path-to-regexp 0.1.13, through express 4.22.3 | Production |
| 3 | express 4.21.1 | body-parser 1.20.3 | CVE-2026-111181 (GHSA-27r3-jxmh-p828), DoS through trailing bytes after a compressed body | High | body-parser 1.20.9, through express 4.22.3 | Production. `express.json()` is used in `src/app.ts`. |
| 4 | express 4.21.1 | body-parser 1.20.3 | CVE-2026-12590 (GHSA-v422-hmwv-36x6), an invalid `limit` value disables size enforcement | Low | body-parser 1.20.6 | Production. The project uses a valid `limit: '1mb'`, which reduces the impact. |
| 5 | express 4.21.1 | qs 6.13.0 | CVE-2025-15284 (GHSA-6rw7-vpxm-498p), CVE-2026-2391 (GHSA-w7fw-mjwx-w883), CVE-2026-82417 (GHSA-4mjr-xmp4-gh2g), plus GHSA-q8mj-m7cp-5q26 and GHSA-6pq8-jhm2-2vcw | Medium / Low | qs 6.16.1 or later, through express 4.22.3 | Production. Query-string parsing happens on every request. |
| 6 | express 4.21.1 | proxy-addr | CVE-2026-90711 (GHSA-jqcg-44mw-7w3h), IP spoofing through IPv4-mapped IPv6 trust subnet | Critical | proxy-addr 2.0.8, through express 4.22.3 | Production. Exploitable only when `trust proxy` is set to a subnet. `trust proxy` is not configured in `src/app.ts`, which lowers the practical risk. |
| 7 | zod 3.23.8 | zod | CVE-2023-54404 (GHSA-mrhx-c7xc-m3w5), memory exhaustion while validating oversized constrained collections | High | zod 4.6.6. There is no 3.x fix; `zod@3.25.76` is also in the affected range `<4.6.6`. | Production. Every request body, query and params passes through Zod (`src/middlewares/validate.middleware.ts`). |
| 8 | uuid 11.0.3 | uuid | CVE-2026-41907 (GHSA-w5hq-g745-h8pq), missing buffer bounds check in v3/v5/v6 when `buf` is provided | Medium | uuid 11.1.1 | Not reachable. The project calls only `v4()` without a buffer. The vulnerable version is still installed. |
| 9 | bcrypt 5.1.1 | @mapbox/node-pre-gyp 1.0.11, then tar 6.2.1 (deprecated) | CVE-2026-24842 (GHSA-34x7-hfp2-rc4v), CVE-2026-23745 (GHSA-8qq5-rm4j-mr97), CVE-2026-73566 (GHSA-r292-9mhp-454m), plus 9 more node-tar advisories (hardlink/symlink path traversal, DoS) | Critical (aggregate per npm audit), High (individual GHSA) | tar 7.5.21 or later. `bcrypt@6.0.0` no longer depends on node-pre-gyp. | Install and build time, when the prebuilt native binary is downloaded and extracted. This is a supply-chain and CI risk. |
| 10 | vitest 2.1.4 | vitest | CVE-2025-24964 (GHSA-9crc-q9x8-hgqq), RCE when a malicious website is visited while the Vitest API server is listening | Critical | vitest 2.1.9 | Development and CI only |
| 11 | vitest 2.1.4 | vitest | CVE-2026-47429 (GHSA-5xrq-8626-4rwp), arbitrary file read and execute when the UI server is listening | Critical | vitest 3.2.6 | Development only, when the UI or API server is enabled |
| 12 | vitest 2.1.4 | @vitest/mocker | CVE-2026-84373 (GHSA-82fw-gwwq-j7x9), CVE-2026-112949 (GHSA-qxg6-89mg-rqv8) | Medium | vitest 4.1.12 | Development only |
| 13 | vitest 2.1.4 | tinypool | CVE-2026-104848 (GHSA-5gmw-xhrv-c9v3), CVE-2026-104849 (GHSA-85c8-ppgw-ccpr), prototype-pollution gadget leading to RCE | Critical | tinypool 2.1.2 | Development and CI only |
| 14 | vitest 2.1.4 | vite 5.4.21 and vite-node | Multiple GHSA advisories (path traversal, `server.fs.deny` bypass on Windows, launch-editor issues) | High | vite 6.4.4 or later | Development only. Applies to the Windows workstation used here. |
| 15 | tsx 4.19.2, vitest 2.1.4 | esbuild 0.23.1 | GHSA-67mh-4wv8-2f99 (no CVE assigned), development server answers cross-origin requests | Medium | esbuild 0.25.0, through tsx 4.23.15 | Development only (`npm run dev`) |
| 16 | supertest 7.0.0 | form-data 4.0.5 | CVE-2026-12143 (GHSA-hmw2-7cc7-3qxx), CRLF injection in multipart field names | High | form-data 4.0.6 | Tests only |
| 17 | eslint 8.57.1, @typescript-eslint/* 8.13.0 | minimatch, brace-expansion | CVE-2026-118764 (GHSA-g3hv-75wg-m249) and multiple brace-expansion ReDoS/DoS advisories | Medium / High | No fix available on the ESLint 8 line | Lint tooling only |
| 18 | pino-pretty 11.3.0 | fast-copy 3.0.x | GHSA-jggr-w7fw-pc2j (no CVE assigned), stack exhaustion | Medium | fast-copy 3.1.0 | Development logging only |

The `npm audit` totals are: critical 4, high 12, moderate 22, for 38 packages in all.

### 2.2 Deprecated, legacy and end-of-life core dependencies

| Dependency | Current | Status | Evidence |
|------------|---------|--------|----------|
| eslint | 8.57.1 | End of life (since 2024-10-05). The registry marks it deprecated: "This version is no longer supported." | eslint.org/version-support. ESLint 9 also reached end of life on 2026-08-06. The supported line is 10.x (latest 10.14.0). |
| @prisma/client / prisma | 5.22.0 | Legacy, with two majors behind (6.x and 7.x). The 5.x line has had no release since 2024-11-05, which is more than 1 year without maintenance. | Released 2024-11-05. Prisma 6.0.0 followed on 2024-11-28 and 7.0.0 on 2025-11-19. Latest stable is 7.10.1 (2026-10-15). |
| bcrypt | 5.1.1 | Legacy. The last 5.x release was on 2023-08-16, more than 3 years ago. | bcrypt 6.0.0 was released on 2025-05-11. The 5.x line depends on deprecated `tar@6.2.1`, `rimraf@3`, `glob@7` and `inflight`. |
| zod | 3.23.8 | Legacy major. Zod 4.0.0 was released on 2025-07-09. The final 3.x release is 3.25.76 (2025-07-08). | The open CVE-2023-54404 has no 3.x fix. |
| supertest | 7.0.0 | Deprecated version. The registry message reads "Please upgrade to supertest v7.1.3+". | package-lock.json `deprecated` field |
| @types/uuid | 10.0.0 | Unnecessary. The latest version, 11.0.0, is a deprecated stub: "uuid provides its own type definitions". | npm registry |
| Node.js runtime (`engines: >=20`, local v20.19.5) | 20.x | End of life since 2026-04-30 | Node.js release schedule. Vitest 5.1.0 requires `^22.12.0 \|\| ^24 \|\| >=26`. Prisma 7.10.1 requires `^20.19 \|\| ^22.12 \|\| >=24`. |
| express | 4.21.1 | Legacy major. The 4.x line is still supported, but only its latest release (4.22.3) receives fixes. | expressjs.com/en/support: "only the latest version of any given major release line is supported". Express 5.0.0 was released on 2024-09-10. |

---

## 3. Dependencies

### 3.1 Production dependencies

| Dependency | Current Version | Latest in Current Major | Latest Version (stable) | License | Status |
|------------|-----------------|-------------------------|-------------------------|---------|--------|
| @prisma/client | 5.22.0 | 5.22.0 (frozen) | 7.10.1 | Apache-2.0 | Legacy (2 majors behind, line unmaintained for more than 1 year) |
| bcrypt | 5.1.1 | 5.1.1 (frozen) | 6.0.0 | MIT | Legacy (last 5.x release 2023-08-16, vulnerable `tar` transitive) |
| express | 4.21.1 | 4.22.3 | 5.3.0 | MIT | Outdated and vulnerable (patch available in 4.22.3) |
| jsonwebtoken | 9.0.2 | 9.0.3 | 9.0.3 | MIT | Outdated (patch) |
| pino | 9.5.0 | 9.14.0 | 10.4.0 | MIT | Outdated (1 major behind) |
| pino-http | 10.3.0 | 10.5.0 | 11.0.0 | MIT | Outdated and unused (never imported) |
| uuid | 11.0.3 | 11.1.1 | 14.0.3 | MIT | Outdated and vulnerable (3 majors behind, CVE-2026-41907) |
| zod | 3.23.8 | 3.25.76 | 4.6.7 | MIT | Legacy and vulnerable (CVE-2023-54404, no 3.x fix) |

### 3.2 Development dependencies

| Dependency | Current Version | Latest in Current Major | Latest Version (stable) | License | Status |
|------------|-----------------|-------------------------|-------------------------|---------|--------|
| @types/bcrypt | 5.0.2 | 5.0.2 | 6.0.0 | MIT | Outdated (follows bcrypt major) |
| @types/express | 4.17.21 | 4.17.x | 5.0.6 | MIT | Outdated (follows express major) |
| @types/jsonwebtoken | 9.0.7 | 9.0.10 | 9.0.10 | MIT | Outdated (patch) |
| @types/node | 20.17.6 | 20.19.43 | 26.6.6 | MIT | Outdated (tracks the end-of-life Node 20) |
| @types/supertest | 6.0.2 | 6.0.x | 7.2.1 | MIT | Outdated (1 major behind) |
| @types/uuid | 10.0.0 | 10.0.0 | 11.0.0 (deprecated stub) | MIT | Unnecessary (uuid ships its own types) |
| @typescript-eslint/eslint-plugin | 8.13.0 | 8.72.1 | 8.72.1 | MIT | Outdated (59 minor releases behind) |
| @typescript-eslint/parser | 8.13.0 | 8.72.1 | 8.72.1 | BSD-2-Clause | Outdated (59 minor releases behind) |
| eslint | 8.57.1 | 8.57.1 (end of life) | 10.14.0 | MIT | Deprecated / end of life |
| eslint-config-prettier | 9.1.0 | 9.1.0 | 10.1.8 | MIT | Outdated (1 major behind) |
| pino-pretty | 11.3.0 | 11.x | 13.2.0 | MIT | Outdated (2 majors behind) |
| prettier | 3.3.3 | 3.9.10 | 3.9.10 | MIT | Outdated (minor) |
| prisma (CLI) | 5.22.0 | 5.22.0 (frozen) | 7.10.1 (the `latest` tag is 8.0.0-rc.29, a prerelease) | Apache-2.0 | Legacy |
| supertest | 7.0.0 | 7.3.1 | 7.3.1 | MIT | Deprecated version (registry asks for 7.1.3 or later) |
| tsx | 4.19.2 | 4.23.15 | 4.23.15 | MIT | Outdated and vulnerable (esbuild GHSA-67mh-4wv8-2f99) |
| typescript | 5.6.3 | 5.9.3 | 7.0.2 | Apache-2.0 | Outdated (2 majors behind; TS 7 is the native Go port) |
| vitest | 2.1.4 | 2.1.9 | 5.1.0 | MIT | Outdated and vulnerable (3 majors behind, multiple Critical CVEs) |

### 3.3 Release dates (registry-verified)

| Package@version | Release date |
|-----------------|--------------|
| bcrypt@5.1.1 | 2023-08-16 |
| bcrypt@6.0.0 | 2025-05-11 |
| jsonwebtoken@9.0.2 | 2023-08-30 |
| jsonwebtoken@9.0.3 | 2025-12-04 |
| eslint-config-prettier@9.1.0 | 2023-12-02 |
| zod@3.23.8 | 2024-05-08 |
| zod@4.0.0 | 2025-07-09 |
| @types/uuid@10.0.0 | 2024-06-20 |
| express@5.0.0 | 2024-09-10 |
| express@4.21.1 | 2024-10-08 |
| express@4.22.3 | 2026-09-14 |
| vitest@2.1.4 | 2024-10-28 |
| vitest@2.1.9 | 2025-02-03 |
| @prisma/client@5.22.0 | 2024-11-05 |
| @prisma/client@7.0.0 | 2025-11-19 |
| uuid@11.0.3 | 2024-11-10 |
| uuid@11.1.1 | 2026-04-29 |

### 3.4 License compatibility

| License | Packages | Assessment |
|---------|----------|------------|
| MIT | 21 direct packages | Permissive and compatible with proprietary or private use |
| Apache-2.0 | @prisma/client, prisma, typescript | Permissive. It includes a patent grant and requires NOTICE file preservation when redistributed. |
| BSD-2-Clause | @typescript-eslint/parser | Permissive (development only) |

No GPL, LGPL, AGPL or other copyleft license was detected among the direct dependencies. The project is `private: true` and declares no license of its own. Nothing currently forces a decision, but declaring one should be considered if the project is ever distributed.

---

## 4. Risk Analysis

| Severity | Dependency | Issue | Details |
|----------|------------|-------|---------|
| Critical | vitest 2.1.4 | CVE-2025-24964, CVE-2026-47429 | RCE or arbitrary file read when the Vitest API or UI server is listening. The fix for CVE-2025-24964 is in 2.1.9. CVE-2026-47429 requires 3.2.6 or later. |
| Critical | vitest 2.1.4, via tinypool | CVE-2026-104848, CVE-2026-104849 | A prototype-pollution gadget leads to RCE in worker options. The project runs Vitest with `pool: 'forks'`, so tinypool is in the execution path. |
| Critical (install time) | bcrypt 5.1.1, via @mapbox/node-pre-gyp and tar 6.2.1 | CVE-2026-24842, CVE-2026-23745, CVE-2026-73566 plus 9 more node-tar advisories | Path traversal and arbitrary file overwrite while the native binary archive is extracted during `npm install`. This is a supply-chain risk in CI and developer machines. `tar@6.2.1` is deprecated. |
| High | express 4.21.1, via path-to-regexp 0.1.10 | CVE-2024-52798, CVE-2026-4867 | ReDoS on routes with parameters. The API uses parameterized routes such as `/:id` across all modules. |
| High | express 4.21.1, via body-parser 1.20.3 | CVE-2026-111181 | DoS through trailing bytes after a compressed request body. `express.json()` is applied globally. |
| High | zod 3.23.8 | CVE-2023-54404 | Memory exhaustion when validating oversized constrained collections. `order.schemas.ts` validates arrays of order items from untrusted input. No 3.x fix exists, so a major-version migration is required. |
| High | @prisma/client / prisma 5.22.0 | Legacy, unmaintained line | The line has had no release in about 2 years and is 2 majors behind (7.10.1). Prisma 7 changes the generator (`prisma-client` replaces `prisma-client-js`), introduces `prisma.config.ts` and uses driver adapters. This is the largest single point of failure: every repository, both transactional services, the seed and the test setup depend on it. |
| High | bcrypt 5.1.1 | Unmaintained line (more than 3 years) | It is a native addon. Rebuilds on newer Node versions depend on node-pre-gyp, whose own maintenance has stalled. It is security-critical for password hashing. |
| High | Node.js 20 runtime | End of life on 2026-04-30 | The runtime no longer receives security patches. `engines: ">=20"` still allows it. Current tooling such as vitest 5 already refuses to run on Node 20. |
| High | supertest 7.0.0, via form-data 4.0.5 | CVE-2026-12143 | CRLF injection in multipart field names (tests only). The version is also flagged deprecated by the registry. |
| Medium | express 4.21.1, via qs 6.13.0 | CVE-2025-15284, CVE-2026-2391, CVE-2026-82417 | Query-string DoS through arrayLimit bypass and an attacker-controlled `isBuffer` |
| Medium | express 4.21.1, via proxy-addr | CVE-2026-90711 (rated Critical by GHSA) | IP spoofing applies only when `trust proxy` is set to a subnet. It is not configured in `src/app.ts`, so the effective risk is Medium. It becomes Critical if a reverse proxy configuration is added later. |
| Medium | uuid 11.0.3 | CVE-2026-41907 | Buffer bounds issue in v3/v5/v6. The project uses only `v4()`, so the vulnerable path is not exercised. The fix is in 11.1.1. |
| Medium | eslint 8.57.1 | End of life, deprecated | No further security or compatibility fixes. It carries minimatch and brace-expansion DoS advisories (CVE-2026-118764). It uses the legacy `.eslintrc.json` format, which ESLint 10 no longer supports (flat config only). |
| Medium | tsx 4.19.2, via esbuild 0.23.1 | GHSA-67mh-4wv8-2f99 | The development server accepts cross-origin requests (dev only). The fix is in tsx 4.23.15. |
| Medium | vitest 2.1.4, via vite 5.4.21 | Multiple vite and launch-editor advisories | Windows-specific `server.fs.deny` bypass and an NTLM hash disclosure via UNC paths. The local development machine runs Windows 11. |
| Low | pino-http 10.3.0 | Unused production dependency | Declared in `dependencies` but never imported. It increases the install surface and audit noise without benefit. Request logging is implemented by hand in `src/middlewares/request-logger.middleware.ts`. |
| Low | @types/uuid 10.0.0 | Redundant | uuid 11 bundles its own types. The `@types/uuid` package is a deprecated stub. |
| Low | jsonwebtoken 9.0.2 | Patch behind (9.0.3) | No open CVE affects 9.0.2 directly, and the resolved `jws@3.2.3` is the patched version. `jwt.verify` is called without an explicit `algorithms` allow-list in `src/middlewares/auth.middleware.ts`. jsonwebtoken 9 restricts symmetric secrets to HS* algorithms by default, which mitigates algorithm confusion. |
| Low | pino 9.5.0, pino-pretty 11.3.0 | Outdated | pino 10 and pino-pretty 13 are available. pino-pretty brings in fast-copy GHSA-jggr-w7fw-pc2j (dev only). |
| Low | typescript 5.6.3, prettier 3.3.3, @typescript-eslint 8.13.0 | Outdated tooling | No direct CVEs. TypeScript 7 (the native port) is a significant breaking change for the toolchain. |

### 4.1 Single points of failure

| Dependency | Files depending on it | Impact |
|------------|----------------------|--------|
| @prisma/client | 17 files (all repositories and services, `app.ts`, `config/database.ts`, `error.middleware.ts`, `order.status.ts`, `order.schemas.ts`, `prisma/seed.ts`, `tests/helpers/factories.ts`, `tests/setup.ts`) | Generated model types (`Order`, `Product`, `OrderStatus` and others) are imported directly into the domain and schema layers, so no anti-corruption layer exists. A Prisma major upgrade touches the whole codebase. |
| express | 15 files (all controllers and routes, all middlewares, `app.ts`, `tests/helpers/factories.ts`) | It is the HTTP backbone. Its transitive CVEs affect every endpoint. |
| zod | 9 files (all `*.schemas.ts`, `config/env.ts`, `validate.middleware.ts`, `error.middleware.ts`, `user.routes.ts`) | It validates all inputs and the environment at boot. The CVE is unfixable without a migration to Zod 4, which has breaking API changes in error formatting (`issues`, `ZodTypeAny`). |
| bcrypt | 4 files (`auth.service.ts`, `user.service.ts`, `prisma/seed.ts`, `tests/helpers/factories.ts`) | All credential hashing and verification. Being a native addon, it is the most fragile across Node upgrades. |
| jsonwebtoken | 2 files (`auth.service.ts`, `auth.middleware.ts`) | All authentication and authorization |

### 4.2 Breaking changes in newer majors (for awareness only)

| Dependency | Current to latest | Notable breaking changes relevant to this codebase |
|------------|-------------------|-----------------------------------------------------|
| express | 4 to 5 | `req.query` becomes a read-only getter. `validate.middleware.ts` relies on `Object.assign(req.query, parsedQuery)`, which changes semantics. path-to-regexp v8 route syntax changes (wildcards, optional parameters). Rejected promises in handlers are forwarded to error middleware. `@types/express` 5 is needed. |
| @prisma/client | 5 to 7 | New `prisma-client` generator with a required output path. `prisma.config.ts`. Driver adapters, such as `@prisma/adapter-mariadb` for MySQL. ESM-first client. Minimum Node `^20.19 \|\| ^22.12 \|\| >=24`. Changed `Prisma.PrismaClientKnownRequestError` import paths affect `error.middleware.ts`. |
| zod | 3 to 4 | Error customization API changes, `ZodTypeAny` is replaced by `ZodType`, `.issues` shapes change, and string format helpers move to top-level (`z.email()`). Affects `validate.middleware.ts`, `error.middleware.ts` and all `*.schemas.ts`. |
| bcrypt | 5 to 6 | It drops node-pre-gyp in favor of bundled prebuilds and requires a newer Node. The API is unchanged. |
| uuid | 11 to 14 | Successive majors drop CommonJS and older Node support. The `v4` API is unchanged. |
| vitest | 2 to 5 | Minimum Node 22.12. Pool configuration changes: `poolOptions.forks.singleFork` was reworked in v4. Affects `vitest.config.ts`. |
| eslint | 8 to 10 | `.eslintrc.json` is no longer supported, and flat config (`eslint.config.js`) is mandatory. |
| typescript | 5 to 7 | The native compiler (tsgo). Some `compilerOptions` such as `baseUrl` are deprecated or removed, and `tsconfig.json` uses `baseUrl`. |

### 4.3 Maintenance burden assessment

- **Exact pinning.** With no `^` or `~`, patch-level security fixes such as express 4.22.3 or uuid 11.1.1 are never picked up automatically. Every fix requires a manifest change.
- **Coordinated upgrades.** Three production majors are behind together (Prisma, Zod, Express), and all three are deeply coupled into shared middleware (`error.middleware.ts`, `validate.middleware.ts`). Upgrading them is coordinated work rather than independent bumps.
- **Paired `@types/*` packages.** `@types/express`, `@types/bcrypt`, `@types/node` and `@types/supertest` must move in lockstep with their runtime packages.
- **No automated dependency-update or audit configuration.** No Dependabot or Renovate configuration was found among the audited files.

---

## 5. Unverified Dependencies

| Dependency | Current Version | Reason Not Verified |
|------------|-----------------|---------------------|
| All 25 direct dependencies | See section 3 | Partially unverified. Context7 and Firecrawl were not available in this session. Versions, deprecations and vulnerabilities were verified through the npm registry, `npm audit` and the GitHub Advisory API instead. No package was left without version verification. |
| esbuild (via tsx, vitest) | 0.23.1 | GHSA-67mh-4wv8-2f99 has no CVE identifier assigned in the GitHub Advisory Database. It is reported by GHSA ID only. |
| fast-copy (via pino-pretty) | 3.0.x | GHSA-jggr-w7fw-pc2j has no CVE identifier assigned. It is reported by GHSA ID only. |
| @types/express (4.x line) | 4.17.21 | The newest 4.17.x patch was not queried individually. Only the overall latest (5.0.6) was verified. |
| @types/supertest, pino-pretty (latest within current major) | 6.0.2 / 11.3.0 | Only the overall latest version was verified (7.2.1 / 13.2.0). The newest patch within the current major was not queried. |

---

## 6. Critical File Analysis

These are the 10 most critical files that depend on risky dependencies, ranked by business impact, security sensitivity and dependency concentration.

| Rank | File | Risky dependencies | Why it is critical |
|------|------|--------------------|--------------------|
| 1 | `src/app.ts` | express 4.21.1 (path-to-regexp, body-parser, qs, proxy-addr CVEs), @prisma/client 5.22.0 | It is the composition root. It builds the Express app, mounts `express.json({ limit: '1mb' })` (body-parser CVE-2026-111181) and wires every repository to the Prisma client. Every request passes through this pipeline, so all express transitive CVEs surface here. If `trust proxy` is ever added here, CVE-2026-90711 becomes directly exploitable. |
| 2 | `src/middlewares/validate.middleware.ts` | zod 3.23.8 (CVE-2023-54404), express 4 (`req.query` semantics) | It validates the body, query and params for all routes. It is the entry point for the Zod memory-exhaustion CVE. It is coupled to Zod 3 types (`ZodTypeAny`, `ZodError.issues`) and to mutable `req.query` through `Object.assign(req.query, ...)`, which Express 5 changes. It sits on the critical path of both the Zod and Express majors. |
| 3 | `src/middlewares/auth.middleware.ts` | jsonwebtoken 9.0.2, express 4 | It is the authentication gate for every protected route. It calls `jwt.verify` without an explicit `algorithms` allow-list, and it augments the `express-serve-static-core` `Request` type, which is coupled to the `@types/express` 4 layout. A compromise here bypasses authorization for the whole API. |
| 4 | `src/modules/auth/auth.service.ts` | bcrypt 5.1.1 (unmaintained, vulnerable tar transitive), jsonwebtoken 9.0.2 | It handles credential verification (`bcrypt.compare`) and token issuance (`jwt.sign`). It is the highest-sensitivity business logic and concentrates two security-critical libraries. |
| 5 | `src/modules/orders/order.service.ts` | @prisma/client 5.22.0 (legacy) | It is the core business domain (255 lines, the largest service). It uses interactive transactions (`prisma.$transaction(async (tx) => ...)`) for order creation and status changes, and it imports multiple Prisma-generated types. Prisma major changes to transaction and client typing affect revenue-critical flows directly. |
| 6 | `src/middlewares/error.middleware.ts` | @prisma/client 5.22.0 (`Prisma.PrismaClientKnownRequestError`), zod 3.23.8 (`ZodError`), express 4 | It is the global error translator. It depends on internal error classes and codes (P2002, P2025) from Prisma 5 and on `ZodError` from Zod 3. Three legacy majors meet in one file, and a mismatch after any upgrade turns 4xx responses into 500s. |
| 7 | `src/config/database.ts` | @prisma/client 5.22.0 | It is the Prisma client singleton used by the app, the tests (`tests/setup.ts`) and indirectly the seed. Prisma 7 requires a driver adapter and a new generator output, so this file is the first breaking point. Every database feature depends on it. |
| 8 | `prisma/schema.prisma` | prisma 5.22.0 (`prisma-client-js` generator) | It is the data-model source of truth and drives migrations. The `prisma-client-js` generator and the `url` / `shadowDatabaseUrl` datasource fields are Prisma 5/6 conventions that move to `prisma.config.ts` in Prisma 7. A schema or migration mismatch risks data integrity. |
| 9 | `src/modules/users/user.service.ts` | bcrypt 5.1.1, @prisma/client 5.22.0 | It handles user creation and password hashing (`bcrypt.hash(input.password, BCRYPT_ROUNDS)`). It depends on a native addon on an unmaintained line. A build failure of bcrypt on a newer Node runtime breaks user registration and login. |
| 10 | `src/config/env.ts` | zod 3.23.8 | It validates environment variables at boot, including `JWT_SECRET` (minimum 16 characters) and `DATABASE_URL`, and exits the process on failure. Any Zod 4 API change in `.issues` or `.coerce` behavior affects application startup and the security configuration. |

Also relevant, though ranked lower: `src/modules/orders/order.schemas.ts` (Zod and Prisma `OrderStatus` coupling, and the array-of-items validation that is the most direct Zod DoS vector), `src/routes/index.ts` (path-to-regexp route definitions), `tests/setup.ts` and `vitest.config.ts` (vitest 2.1.4 Critical CVEs, `poolOptions.forks.singleFork`), `prisma/seed.ts` (bcrypt and Prisma).

---

## 7. Integration Notes

| Dependency | How it is used | Coupling level |
|------------|----------------|----------------|
| express | HTTP server and router. `buildApp()` in `src/app.ts` and `Router()` in `src/routes/index.ts` and each `*.routes.ts`. `RequestHandler` / `ErrorRequestHandler` types in all controllers and middlewares. `express.json({ limit: '1mb' })`. `x-powered-by` is disabled. `trust proxy` is not set. | High. The Express type is used in every controller and there is no framework abstraction. |
| @prisma/client | `PrismaClient` singleton (`src/config/database.ts`), injected into the repositories (customer, order, product, user) and into `OrderService`. Generated model and enum types are used directly in the domain, the schemas and the tests. `$transaction` is used in array form (pagination) and in interactive form (orders). | Very high. Generated types leak into the domain layer and no repository interface isolates them. |
| prisma (CLI) | Migrations (`db:migrate`, `db:reset`), seeding (`prisma.seed` uses tsx), client generation. MySQL provider with a shadow database. | High (build and dev workflow) |
| zod | Input schemas per module (`*.schemas.ts`), the generic `validate()` middleware, environment validation (`config/env.ts`), ZodError translation in `error.middleware.ts`, an inline schema in `user.routes.ts`. | High |
| jsonwebtoken | `jwt.sign` with `expiresIn` from env (`auth.service.ts`) and `jwt.verify` with a shared HS secret (`auth.middleware.ts`). | Low. Two call sites, easy to isolate. |
| bcrypt | `bcrypt.hash` (user creation, seed, test factories) and `bcrypt.compare` (login). Rounds come from a `BCRYPT_ROUNDS` constant, with 10 used in the seed and tests. | Low in code, high operationally because it is a native addon. |
| pino | Central logger (`src/shared/logger/index.ts`) with redaction of auth headers, passwords and tokens, ISO timestamps, and a `pino-pretty` transport in development. | Low (single wrapper module) |
| pino-pretty | Development-only transport target, referenced by string in the logger config. | Low |
| pino-http | Not used. The request logging is a custom middleware (`request-logger.middleware.ts`) built on `pino` directly. | None (dead dependency) |
| uuid | `v4()` generates a request ID when the `x-request-id` header is absent (`request-logger.middleware.ts`). It could be replaced by the Node built-in `crypto.randomUUID()`. | Very low |
| vitest | Test runner (`vitest.config.ts`): forks pool, single fork, serial files, `tests/setup.ts` truncates tables before each test. | Medium |
| supertest | HTTP assertions against `buildApp()` in `tests/auth.test.ts`, `tests/orders.test.ts` and `tests/helpers/factories.ts`. | Low |
| tsx | Development runner (`dev`, `db:seed`, the prisma seed hook). | Low |
| typescript | Compiler (`build` uses `tsconfig.build.json`). Strict mode, `moduleResolution: Bundler`, `baseUrl` with paths. | Medium |
| eslint, @typescript-eslint/*, eslint-config-prettier | Linting through the legacy `.eslintrc.json` (eslintrc format). | Low (tooling) |
| prettier | Formatting (`.prettierrc`, `.prettierignore`). | Low |
| @types/* | Type definitions for express 4, bcrypt 5, jsonwebtoken 9, node 20, supertest 6, uuid 10 (redundant). | Low, but each must track its runtime major. |

No forks, `patch-package` patches, vendored copies or `overrides` / `resolutions` were found in `package.json`. Transitive vulnerabilities therefore cannot be mitigated without changing direct dependency versions.

### Actionable next steps (reporting only, no changes performed)

1. **Production, highest priority.** Remediate the express transitive CVEs (CVE-2024-52798, CVE-2026-4867, CVE-2026-111181, CVE-2025-15284, CVE-2026-82417, CVE-2026-90711). A patched release exists within the current major (`express@4.22.3`).
2. **Production.** Address zod CVE-2023-54404. A fix exists only in `zod@4.6.6` or later, so plan the Zod 3 to 4 migration around `validate.middleware.ts`, `error.middleware.ts` and the `*.schemas.ts` files.
3. **Supply chain.** Assess the `bcrypt@5.1.1` install-time exposure through `tar@6.2.1` (CVE-2026-24842, CVE-2026-23745, CVE-2026-73566). `bcrypt@6.0.0` removes the node-pre-gyp and tar dependency chain.
4. **Developer and CI.** Address the vitest Critical CVEs (CVE-2025-24964 is fixed in 2.1.9; CVE-2026-47429, CVE-2026-104848 and CVE-2026-104849 need newer lines). Do not run the Vitest UI or API server on networked machines until then.
5. **Runtime.** Node.js 20 is end of life (2026-04-30). The `engines` constraint `>=20` and the local Node v20.19.5 should be reviewed against Node 22 or 24 LTS, which several current dependency majors already require.
6. **Legacy platform.** Track the Prisma 5 to 7 migration as the largest maintenance item, given its 17-file footprint.
7. **Hygiene.** Remove or justify the unused `pino-http` and the redundant `@types/uuid`. Bring `supertest` to 7.1.3 or later per the registry deprecation notice. Plan the move from end-of-life ESLint 8 to a supported line with flat config.
8. **Process.** Consider an automated dependency-update tool (Dependabot or Renovate) and an `npm audit` gate in CI, given the exact-pinning strategy.
