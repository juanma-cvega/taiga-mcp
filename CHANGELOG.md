# CHANGELOG

<!-- version list -->

## v1.4.1 (2026-07-26)

### Bug Fixes

- **deps**: Update mcp[cli] requirement from >=1.27.2 to >=1.28.1
  ([#8](https://github.com/juanma-cvega/taiga-mcp/pull/8),
  [`d2c8ea4`](https://github.com/juanma-cvega/taiga-mcp/commit/d2c8ea496dd384c774b4705cf9cacc0a1951c413))

### Chores

- Use a neutral sample project in test fixtures
  ([#9](https://github.com/juanma-cvega/taiga-mcp/pull/9),
  [`1496d75`](https://github.com/juanma-cvega/taiga-mcp/commit/1496d7501cad0f72981f19de4ba7d0448f56b0c3))

### Continuous Integration

- Add a Dependabot configuration for uv and GitHub Actions
  ([#4](https://github.com/juanma-cvega/taiga-mcp/pull/4),
  [`4975ea3`](https://github.com/juanma-cvega/taiga-mcp/commit/4975ea355a2ca9dbb5264321a6a7500de1ae0583))

- Fix Dependabot prefixes so runtime bumps release and dev bumps don't
  ([#10](https://github.com/juanma-cvega/taiga-mcp/pull/10),
  [`df98056`](https://github.com/juanma-cvega/taiga-mcp/commit/df98056e357fedb6279650b9680f0ab1cee7884b))

- Mint the release token with client-id, not the deprecated app-id
  ([#5](https://github.com/juanma-cvega/taiga-mcp/pull/5),
  [`226c2a2`](https://github.com/juanma-cvega/taiga-mcp/commit/226c2a2b73987666c18f4b7903118a87b6850b9b))

- Release runtime dependency bumps, not dev or workflow ones
  ([#10](https://github.com/juanma-cvega/taiga-mcp/pull/10),
  [`df98056`](https://github.com/juanma-cvega/taiga-mcp/commit/df98056e357fedb6279650b9680f0ab1cee7884b))

- Run the release gate on pull requests as a non-blocking check
  ([#11](https://github.com/juanma-cvega/taiga-mcp/pull/11),
  [`31035c0`](https://github.com/juanma-cvega/taiga-mcp/commit/31035c0820c60f9b4a8aa18ebf436515e1a86869))

- Stop doubling the Dependabot scope and isolate action majors
  ([#10](https://github.com/juanma-cvega/taiga-mcp/pull/10),
  [`df98056`](https://github.com/juanma-cvega/taiga-mcp/commit/df98056e357fedb6279650b9680f0ab1cee7884b))


## v1.4.0 (2026-07-26)

### Chores

- Add CODEOWNERS assigning ownership of the repo
  ([`6273e29`](https://github.com/juanma-cvega/taiga-mcp/commit/6273e29dddff09af5ae2d12176b9e90f79c8bf9b))

### Continuous Integration

- Push the release as a GitHub App so it clears the main ruleset
  ([#3](https://github.com/juanma-cvega/taiga-mcp/pull/3),
  [`c8760cf`](https://github.com/juanma-cvega/taiga-mcp/commit/c8760cfa9aaa1a879bac5b3ce63b848c373c5176))

- Re-lock uv.lock inside the release so it stops lagging a version
  ([#2](https://github.com/juanma-cvega/taiga-mcp/pull/2),
  [`79779e4`](https://github.com/juanma-cvega/taiga-mcp/commit/79779e400a379838362c16f1708bf1bba63a7cb4))

### Features

- Let update_story attach a story to an epic
  ([#2](https://github.com/juanma-cvega/taiga-mcp/pull/2),
  [`79779e4`](https://github.com/juanma-cvega/taiga-mcp/commit/79779e400a379838362c16f1708bf1bba63a7cb4))


## v1.3.0 (2026-07-24)

### Features

- Add tool to reorder backlog stories for prioritisation
  ([`6d66a6e`](https://github.com/juanma-cvega/taiga-mcp/commit/6d66a6e07acbbc5103174bdfc31c4a2725176cba))


## v1.2.0 (2026-07-23)

### Continuous Integration

- Stop attaching assets to the release; embrace immutable releases
  ([`d060d99`](https://github.com/juanma-cvega/taiga-mcp/commit/d060d998d4d9936b72f2c1660bdd9a59e4133e34))

### Features

- Add tools to read and write comments on stories, epics and tasks
  ([`337e939`](https://github.com/juanma-cvega/taiga-mcp/commit/337e9394dc5eef395768328b71da0f4b33dca78e))


## v1.1.0 (2026-07-17)

### Bug Fixes

- Install uv inside the release build command
  ([`b701c69`](https://github.com/juanma-cvega/taiga-mcp/commit/b701c6947b0e97d175e4735689a615afeb100c5a))

### Chores

- Bump version to 1.1.0
  ([`4aec663`](https://github.com/juanma-cvega/taiga-mcp/commit/4aec6637ffb58892ac20ea495bfccd747a82b6ec))

### Continuous Integration

- Release automatically from the conventional commits on push to main
  ([`555477b`](https://github.com/juanma-cvega/taiga-mcp/commit/555477bbb4136d0488305bf2d3be42d71b84379b))

### Features

- Add sprint tools and a story-to-backlog move
  ([`c768633`](https://github.com/juanma-cvega/taiga-mcp/commit/c7686330f142d6ba7dc04fa6d9a345e36f2e8073))


## v1.0.0 (2026-07-10)

- Initial Release
