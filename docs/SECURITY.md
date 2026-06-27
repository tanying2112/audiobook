# Security Policy

## Reporting a Vulnerability
If you discover a security vulnerability in this project, please **do not** open a public issue. Instead, follow these steps:

1. **Email** the security team at `security@audiobook-studio.org` (or the email listed in the `README.md`).
2. Provide a clear description of the vulnerability, steps to reproduce, and any potential impact.
3. Allow us reasonable time to investigate and address the issue before any public disclosure.

## Supported Versions
We support the latest stable release of the project. Older versions may receive limited security updates.

## Security Practices
- All secret keys and credentials must be stored in `.env` files and never committed to the repository. The `detect-secrets` pre‑commit hook enforces this.
- Dependencies are regularly scanned using **Dependabot** and **bandit**.
- Docker images are built from a minimal base image and scanned for known CVEs.
- Continuous Integration runs security checks on each pull request.

## Policy Updates
This security policy may be updated from time to time. Please refer to the latest version in the repository.
