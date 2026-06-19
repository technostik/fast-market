# common/auth

## 🎯 Purpose
Base interface for OAuth and API authentication providers. Defines the contract that all fast-market auth clients must satisfy.

## 🏗️ Essential Components
- `base.py` — `AuthProvider` ABC with a single abstract method `get_client() -> Any`

## 📋 Core Responsibilities
- Declare the minimum contract for authentication providers
- Force implementors to return an authenticated API client

## 🔗 Dependencies & Integration
- Imports from: none (stdlib only)
- Used by: `common.youtube.auth.YouTubeOAuth` — extends `AuthProvider`
- External deps: none

## ✅ Do's
- Subclass `AuthProvider` for every new external service that needs OAuth or API key auth
- Return the authenticated SDK client object from `get_client()`

## ❌ Don'ts
- Do not add service-specific logic here — keep it in the concrete subclass
- Do not add multiple abstract methods — the contract is intentionally minimal

## 🛠️ Extension Points
- To add a new auth provider (e.g., Google Sheets): create `common/<service>/auth.py` with a class extending `AuthProvider`

## 📚 Related Documentation
- See `README.md` for usage and CLI reference
- See `common/youtube/AGENTS.md` for the YouTube OAuth implementation
