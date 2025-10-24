# Release Process

This document describes the automated release process for Sentinel AI using release-please.

## Overview

Release-please automates the versioning and changelog generation based on [Conventional Commits](https://www.conventionalcommits.org/). It creates and maintains a release PR that updates the version and changelog as you merge commits to the main branch.

## How It Works

1. **Commit with Conventional Commit format** to the `main` branch
2. **Release-please automatically creates/updates a release PR** with:
   - Updated version in `pyproject.toml`
   - Generated `CHANGELOG.md`
   - Release notes
3. **When you merge the release PR**:
   - A GitHub release is created
   - A git tag is created (e.g., `v0.2.0`)
   - The changelog is finalized

## Conventional Commit Format

Follow this format for your commit messages:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Commit Types

| Type       | Version Bump  | Description                                  | Example                                |
| ---------- | ------------- | -------------------------------------------- | -------------------------------------- |
| `feat`     | Minor (0.x.0) | New feature                                  | `feat: add context menu for flagging`  |
| `fix`      | Patch (0.0.x) | Bug fix                                      | `fix: resolve timeout in LLM calls`    |
| `perf`     | Patch (0.0.x) | Performance improvement                      | `perf: optimize heuristics matching`   |
| `docs`     | No bump       | Documentation changes                        | `docs: update configuration guide`     |
| `refactor` | No bump       | Code refactoring                             | `refactor: simplify moderation logic`  |
| `test`     | No bump       | Adding or updating tests                     | `test: add unit tests for LLM service` |
| `build`    | No bump       | Build system or dependency changes           | `build: update discord.py to 2.4.0`    |
| `ci`       | No bump       | CI/CD changes                                | `ci: add deployment workflow`          |
| `chore`    | No bump       | Other changes that don't modify src or tests | `chore: update .gitignore`             |

### Breaking Changes

To trigger a major version bump (x.0.0), add `BREAKING CHANGE:` in the commit footer or add `!` after the type:

```bash
feat!: redesign slash command structure

BREAKING CHANGE: All slash commands now require guild permissions
```

### Examples

**Feature (minor bump):**

```bash
git commit -m "feat: add automatic thread creation in busy channels"
```

**Bug fix (patch bump):**

```bash
git commit -m "fix: prevent duplicate moderation actions"
```

**Performance improvement (patch bump):**

```bash
git commit -m "perf: cache heuristics in memory"
```

**Documentation (no bump):**

```bash
git commit -m "docs: add examples to heuristics system guide"
```

**Breaking change (major bump):**

```bash
git commit -m "feat!: migrate to new database schema

BREAKING CHANGE: Requires running migration script before upgrading"
```

## Workflow

### 1. Make Changes and Commit

```bash
# Make your changes
git add .
git commit -m "feat: add new moderation action - mute"
git push origin main
```

### 2. Release-please Creates/Updates PR

After pushing to `main`, release-please will:

- Create a new PR titled `chore: release X.Y.Z` (if one doesn't exist)
- Or update the existing release PR with your new changes

The PR will include:

- Updated version in `pyproject.toml`
- Generated/updated `CHANGELOG.md`
- Commit history since last release

### 3. Review and Merge Release PR

When you're ready to release:

1. **Review the release PR** - Check the version bump and changelog
2. **Merge the PR** - Release-please will:
   - Create a GitHub release
   - Create a git tag (e.g., `v0.2.0`)
   - Publish the changelog
   - Automatically publish to PyPI (if `PYPI_API_TOKEN` secret is configured)

### 4. PyPI Publishing

The workflow automatically publishes to PyPI when a release is created. To set this up:

1. **Create a PyPI API token** at [pypi.org/manage/account/token/](https://pypi.org/manage/account/token/)
2. **Add the token to GitHub Secrets**:
   - Go to your repository → Settings → Secrets and variables → Actions
   - Create a new secret named `PYPI_API_TOKEN`
   - Paste your PyPI token as the value

The package will be automatically published when you merge a release PR.

### 5. Optional: Manual Deployment

After the release is created, you can manually deploy to production if needed:

```bash
# Pull the latest tags
git pull --tags

# Deploy to Fly.io
fly deploy
```

## Version Numbering

Sentinel AI follows [Semantic Versioning 2.0.0](https://semver.org/):

- **Major (x.0.0)**: Breaking changes
- **Minor (0.x.0)**: New features (backward compatible)
- **Patch (0.0.x)**: Bug fixes and improvements

Current version is managed in:

- `pyproject.toml` → `project.version`
- `.release-please-manifest.json` → release-please tracking

## Configuration Files

- **`.github/workflows/release-please.yml`** - GitHub Actions workflow with PyPI publishing
- **`.github/release-please-config.json`** - Release-please configuration
- **`.github/.release-please-manifest.json`** - Version tracking

## GitHub Secrets Required

For automatic PyPI publishing, you need to configure:

- **`PYPI_API_TOKEN`** - API token from PyPI for publishing packages
  - Create at: [pypi.org/manage/account/token/](https://pypi.org/manage/account/token/)
  - Scope: "Entire account" or specific to "sentinel-ai" project
  - Add to: Repository Settings → Secrets and variables → Actions

## Troubleshooting

### Release PR not created

- Ensure commits follow conventional commit format
- Check that commits are on the `main` branch
- Verify GitHub Actions has proper permissions

### Wrong version bump

- Review your commit messages for correct types
- Use `!` or `BREAKING CHANGE:` for major bumps
- Use `feat:` for minor bumps
- Use `fix:` or `perf:` for patch bumps

### Need to skip a release

You can close the release PR without merging. Release-please will continue to update it with new commits.

### Manual version override

If you need to manually set a version:

1. Update `.release-please-manifest.json`
2. Commit with `chore: release X.Y.Z`
3. Release-please will use this version

## Best Practices

1. **Write clear commit messages** - They become your changelog
2. **Group related changes** - Bundle related commits before releasing
3. **Review release PRs** - Check changelog accuracy before merging
4. **Tag major changes** - Use breaking change notation for APIs changes
5. **Keep changelog clean** - Only merge commits that add value to changelog

## Additional Resources

- [Release-please Documentation](https://github.com/googleapis/release-please)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
