#!/bin/sh
# Pre-commit: block a commit whose staged changes add an API key or token.
# Rules: .gitleaks.toml (gitleaks defaults + Render + Gemini). A missing gitleaks fails loudly on
# purpose: a check that silently skips is how a Render key reached git history three times.
if ! command -v gitleaks >/dev/null 2>&1; then
  # Windows: VS Code's Commit button runs git with the PATH VS Code started with, which can miss a
  # winget install. Look in winget's own folders before giving up (still fails loudly if absent).
  for dir in "$LOCALAPPDATA/Microsoft/WinGet/Links" "$LOCALAPPDATA"/Microsoft/WinGet/Packages/Gitleaks.Gitleaks_*; do
    if [ -x "$dir/gitleaks.exe" ] || [ -x "$dir/gitleaks" ]; then
      PATH="$dir:$PATH"
      break
    fi
  done
fi
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "gitleaks is not installed, so the secret check cannot run."
  echo "Install it once: brew install gitleaks (Mac) / winget install Gitleaks.Gitleaks (Windows)"
  exit 1
fi
exec gitleaks git --staged --redact --no-banner --config .gitleaks.toml
