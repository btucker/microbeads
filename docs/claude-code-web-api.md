# Claude Code Web API - Reverse Engineering Documentation

This document details the Claude Code Web API used to launch and manage Claude Code agents via `claude.ai/code`.

## Overview

Claude Code Web is Anthropic's browser-based interface for running AI coding agents. It launched in October 2025 and is available to Pro, Max ($100, $200/month) subscribers.

## API Endpoints

### 1. Telemetry Endpoint

**Endpoint:** `POST https://a-api.anthropic.com/v1/t`

Used for analytics/telemetry tracking. Sends events like `claudeai.code.composer.session_creation_started`.

**Response:** `{"success": true}` (21 bytes)

---

### 2. Session Creation Endpoint (Main API)

**Endpoint:** `POST https://claude.ai/v1/sessions`

This is the primary endpoint for creating new Claude Code Web agent sessions.

#### Required Headers

```http
:authority: claude.ai
:method: POST
:path: /v1/sessions
:scheme: https
content-type: application/json
anthropic-version: 2023-06-01
anthropic-beta: ccr-byoc-2025-07-29
anthropic-client-feature: ccr
anthropic-client-platform: web_claude_ai
anthropic-client-version: 1.0.0
anthropic-client-sha: <commit_sha>
anthropic-device-id: <uuid>
anthropic-anonymous-id: claudeai.v1.<uuid>
x-organization-uuid: <organization_uuid>
origin: https://claude.ai
referer: https://claude.ai/code
```

#### Authentication

Authentication is via cookies:
- `sessionKey`: `sk-ant-sid01-...` (primary session authentication)
- `anthropic-device-id`: Device UUID
- `lastActiveOrg`: Organization UUID
- `ajs_user_id`: User account UUID

#### Request Body

```json
{
  "title": "Task title/description",
  "events": [
    {
      "type": "event",
      "data": {
        "uuid": "<message_uuid>",
        "session_id": "",
        "type": "user",
        "parent_tool_use_id": null,
        "message": {
          "role": "user",
          "content": "Your prompt/task for the agent"
        }
      }
    }
  ],
  "environment_id": "env_<environment_id>",
  "session_context": {
    "sources": [
      {
        "type": "git_repository",
        "url": "https://github.com/<owner>/<repo>",
        "revision": "refs/heads/main"
      }
    ],
    "outcomes": [
      {
        "type": "git_repository",
        "git_info": {
          "type": "github",
          "repo": "<owner>/<repo>",
          "branches": ["claude/<branch-name>"]
        }
      }
    ],
    "model": "claude-opus-4-5-20251101"
  }
}
```

#### Request Body Fields

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Display title for the session |
| `events` | array | Initial events/messages for the session |
| `events[].data.uuid` | string | Unique UUID for this message |
| `events[].data.session_id` | string | Empty for new sessions |
| `events[].data.type` | string | Message type: `"user"` |
| `events[].data.message.role` | string | `"user"` or `"assistant"` |
| `events[].data.message.content` | string | The actual message content |
| `environment_id` | string | Environment identifier (format: `env_<id>`) |
| `session_context.sources` | array | Source repositories to clone |
| `session_context.outcomes` | array | Output configuration (branches to push to) |
| `session_context.model` | string | Model to use |

#### Available Models

- `claude-opus-4-5-20251101` - Opus 4.5 (most capable)
- `claude-sonnet-4-5-20250929` - Sonnet 4.5 (balanced)
- Other Claude 3.x/4.x models

#### Response

```json
{
  "created_at": "2026-01-22T18:13:50.883252551Z",
  "environment_id": "env_011CUM4qmvgh4D6N5PBcJDXw",
  "id": "session_01KesSu5V2XYB1Wnsdq7xfSo",
  "origin": "web_claude_ai",
  "session_context": {
    "allowed_tools": [],
    "cwd": "",
    "disallowed_tools": [],
    "knowledge_base_ids": [],
    "model": "claude-opus-4-5-20251101",
    "outcomes": [
      {
        "git_info": {
          "branches": ["claude/reverse-engineer-code-web-api-ZrnbD"],
          "repo": "btucker/microbeads",
          "type": "github"
        },
        "type": "git_repository"
      }
    ],
    "sources": [
      {
        "revision": "refs/heads/main",
        "type": "git_repository",
        "url": "https://github.com/btucker/microbeads"
      }
    ]
  },
  "session_status": "running",
  "title": "Reverse engineer Claude Code Web API",
  "type": "internal_session",
  "updated_at": "2026-01-22T18:13:50.883252551Z"
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Session ID (format: `session_<id>`) |
| `session_status` | string | `"running"`, `"completed"`, etc. |
| `type` | string | `"internal_session"` |
| `origin` | string | `"web_claude_ai"` |
| `environment_id` | string | Environment the session runs in |
| `session_context.allowed_tools` | array | Tools the agent can use |
| `session_context.disallowed_tools` | array | Restricted tools |
| `session_context.knowledge_base_ids` | array | Connected knowledge bases |

---

## Key Concepts

### Environment ID

The `environment_id` represents a cloud compute environment where Claude Code runs. Format: `env_<base62_id>`

### Session Context

Defines the working context for the agent:
- **Sources**: Repositories to clone and work with
- **Outcomes**: Where to push results (branches)
- **Model**: Which Claude model to use

### Beta Features

The `anthropic-beta: ccr-byoc-2025-07-29` header enables "Claude Code Remote - Bring Your Own Compute" features.

---

## Example: Creating a New Agent Session

```python
import requests
import uuid

def create_claude_code_session(
    title: str,
    prompt: str,
    repo_url: str,
    repo_name: str,
    session_key: str,
    organization_uuid: str,
    environment_id: str,
    model: str = "claude-sonnet-4-5-20250929"
):
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "ccr-byoc-2025-07-29",
        "anthropic-client-feature": "ccr",
        "anthropic-client-platform": "web_claude_ai",
        "anthropic-client-version": "1.0.0",
        "x-organization-uuid": organization_uuid,
        "Origin": "https://claude.ai",
        "Referer": "https://claude.ai/code",
    }

    cookies = {
        "sessionKey": session_key,
    }

    branch_name = f"claude/{title.lower().replace(' ', '-')[:30]}"

    payload = {
        "title": title,
        "events": [
            {
                "type": "event",
                "data": {
                    "uuid": str(uuid.uuid4()),
                    "session_id": "",
                    "type": "user",
                    "parent_tool_use_id": None,
                    "message": {
                        "role": "user",
                        "content": prompt
                    }
                }
            }
        ],
        "environment_id": environment_id,
        "session_context": {
            "sources": [
                {
                    "type": "git_repository",
                    "url": repo_url,
                    "revision": "refs/heads/main"
                }
            ],
            "outcomes": [
                {
                    "type": "git_repository",
                    "git_info": {
                        "type": "github",
                        "repo": repo_name,
                        "branches": [branch_name]
                    }
                }
            ],
            "model": model
        }
    }

    response = requests.post(
        "https://claude.ai/v1/sessions",
        headers=headers,
        cookies=cookies,
        json=payload
    )

    return response.json()
```

---

## Related Resources

### Official Documentation
- [Claude Code on the Web](https://code.claude.com/docs/en/claude-code-on-the-web)
- [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Session Management](https://platform.claude.com/docs/en/agent-sdk/sessions)

### Reverse Engineering Projects
- [claude-code-reverse](https://github.com/Yuyz0112/claude-code-reverse) - Visualize Claude Code LLM interactions
- [claude-code-deep-research](https://github.com/Nasairwhite/claude-code-deep-research) - 370 gates, 51 endpoints discovered

### Third-Party Tools
- [coder/agentapi](https://github.com/coder/agentapi) - HTTP API wrapper for Claude Code
- [unofficial-claude-api](https://github.com/st1vms/unofficial-claude-api) - Unofficial API with session gathering

---

## Notes

1. **Authentication Required**: A valid `sessionKey` cookie from an authenticated claude.ai session is required
2. **Subscription Required**: Claude Code Web requires Pro ($20/mo) or Max ($100-200/mo) subscription
3. **Rate Limits**: Subject to Anthropic's usage limits based on subscription tier
4. **CORS**: The API only accepts requests from `https://claude.ai` origin
5. **Branch Naming**: Claude automatically appends a random suffix to branch names (e.g., `-ZrnbD`)

---

---

## Extracting Metadata from Claude Code CLI

If you have access to a running Claude Code CLI session (especially in remote/web mode), you can extract the necessary metadata from environment variables and token files.

### Key Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CLAUDE_CODE_SESSION_ID` | Local session UUID | `960c44e0-ffbc-4b60-8905-9dfd8dc22b5c` |
| `CLAUDE_CODE_REMOTE_SESSION_ID` | Web session ID | `session_01KesSu5V2XYB1Wnsdq7xfSo` |
| `CLAUDE_CODE_CONTAINER_ID` | Container identifier | `container_01MzQT1pvgrTunJ7UhGdz2qa--...` |
| `CLAUDE_CODE_REMOTE` | Whether running in remote mode | `true` |
| `CLAUDE_CODE_ENTRYPOINT` | Entry point mode | `remote` |
| `ANTHROPIC_BASE_URL` | API base URL | `https://api.anthropic.com` |

### Session Ingress Token (JWT)

The most valuable source of metadata is the **session ingress token** located at:

```
/home/claude/.claude/remote/.session_ingress_token
```

Or via environment variable:
```
CLAUDE_SESSION_INGRESS_TOKEN_FILE=/home/claude/.claude/remote/.session_ingress_token
```

This is a JWT (JSON Web Token) with the following payload structure:

```json
{
  "iss": "session-ingress",
  "aud": ["anthropic-api"],
  "session_id": "session_01KesSu5V2XYB1Wnsdq7xfSo",
  "organization_uuid": "99f8780c-c47f-4f24-8fd2-bcf24ac6e3b2",
  "account_uuid": "e2f0e7b8-052c-4b60-98ec-59a9488f6158",
  "account_email": "user@example.com",
  "application": "ccr",
  "iat": 1769105633,
  "exp": 1769120033
}
```

#### JWT Fields

| Field | Description |
|-------|-------------|
| `session_id` | The web session ID for the Claude Code session |
| `organization_uuid` | Organization UUID for billing/permissions |
| `account_uuid` | User's account UUID |
| `account_email` | User's email address |
| `application` | Application identifier (`ccr` = Claude Code Remote) |
| `iat` | Issued at timestamp |
| `exp` | Expiration timestamp |

### Decoding the JWT

```bash
# Decode the JWT payload
cat /home/claude/.claude/remote/.session_ingress_token | \
  cut -d'.' -f2 | \
  base64 -d 2>/dev/null | \
  python3 -m json.tool
```

### Python Script to Extract Metadata

```python
import os
import json
import base64

def get_claude_code_metadata():
    """Extract metadata from Claude Code environment."""
    metadata = {
        "session_id": os.environ.get("CLAUDE_CODE_SESSION_ID"),
        "remote_session_id": os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID"),
        "container_id": os.environ.get("CLAUDE_CODE_CONTAINER_ID"),
        "is_remote": os.environ.get("CLAUDE_CODE_REMOTE") == "true",
        "version": os.environ.get("CLAUDE_CODE_VERSION"),
    }

    # Try to read and decode the JWT
    token_path = os.environ.get(
        "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
        "/home/claude/.claude/remote/.session_ingress_token"
    )

    try:
        with open(token_path, "r") as f:
            token = f.read().strip()

        # Decode JWT payload (middle part)
        payload = token.split(".")[1]
        # Add padding if needed
        payload += "=" * (4 - len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))

        metadata["jwt_payload"] = decoded
        metadata["organization_uuid"] = decoded.get("organization_uuid")
        metadata["account_uuid"] = decoded.get("account_uuid")
        metadata["account_email"] = decoded.get("account_email")
    except Exception as e:
        metadata["jwt_error"] = str(e)

    return metadata

if __name__ == "__main__":
    import json
    print(json.dumps(get_claude_code_metadata(), indent=2))
```

### Using Metadata to Create New Sessions

Once you have the metadata, you can potentially create new sessions by:

1. **Extracting the session key**: The `sessionKey` cookie is needed for authentication
2. **Using the organization UUID**: Required in the `x-organization-uuid` header
3. **Obtaining environment ID**: The `environment_id` appears to be session-specific

**Important Authentication Findings:**

1. **Session Ingress Token Limitations:**
   - Can READ current session: `GET https://api.anthropic.com/v1/sessions/{session_id}` ✓
   - Cannot CREATE new sessions: `POST https://api.anthropic.com/v1/sessions` ✗ (401 Authentication failed)

2. **Required for Creating New Sessions:**
   - Browser session cookies (particularly `sessionKey`) from claude.ai
   - Cloudflare bot protection bypass (browser-based)
   - Valid `environment_id` in request body

3. **API Endpoint Discovery:**
   - The actual API endpoint is `https://api.anthropic.com/v1/sessions` (NOT `claude.ai`)
   - Requires `anthropic-beta: ccr-byoc-2025-07-29` header
   - Uses Bearer authentication: `Authorization: Bearer <session_ingress_token>`

---

## Working API: Query Current Session

From within a Claude Code session, you CAN query your own session:

```python
import urllib.request
import json
import os

token_path = "/home/claude/.claude/remote/.session_ingress_token"
with open(token_path) as f:
    token = f.read().strip()

session_id = os.environ["CLAUDE_CODE_REMOTE_SESSION_ID"]
url = f"https://api.anthropic.com/v1/sessions/{session_id}"

headers = {
    "anthropic-version": "2023-06-01",
    "Authorization": f"Bearer {token}",
    "anthropic-beta": "ccr-byoc-2025-07-29",
}

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as response:
    session_data = json.loads(response.read().decode())
    print(json.dumps(session_data, indent=2))
```

**Response:**
```json
{
  "id": "session_01KesSu5V2XYB1Wnsdq7xfSo",
  "session_status": "running",
  "title": "Your session title",
  "environment_id": "env_...",
  "session_context": { ... }
}
```

---

## Working API: Get Session Events

You can also retrieve all events (messages, tool calls, etc.) from your session:

```python
import urllib.request
import json
import os

token_path = "/home/claude/.claude/remote/.session_ingress_token"
with open(token_path) as f:
    token = f.read().strip()

session_id = os.environ["CLAUDE_CODE_REMOTE_SESSION_ID"]
url = f"https://api.anthropic.com/v1/sessions/{session_id}/events"

headers = {
    "anthropic-version": "2023-06-01",
    "Authorization": f"Bearer {token}",
    "anthropic-beta": "ccr-byoc-2025-07-29",
}

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=15) as response:
    events = json.loads(response.read().decode())
    print(f"Total events: {len(events.get('data', []))}")
```

### Event Types

| Type | Description |
|------|-------------|
| `user` | User messages |
| `assistant` | Claude's responses (with thinking, content) |
| `tool_progress` | Tool execution progress updates |
| `env_manager_log` | Environment manager logs (init, clone, etc.) |
| `system` | System messages |
| `control_response` | Control flow responses |

### User Event Structure

```json
{
  "uuid": "282e4c24-27a9-4efc-879d-ebb11ff4bfa0",
  "type": "user",
  "session_id": "960c44e0-ffbc-4b60-8905-9dfd8dc22b5c",
  "parent_tool_use_id": null,
  "isReplay": true,
  "message": {
    "role": "user",
    "content": "Your message here"
  }
}
```

### Assistant Event Structure

```json
{
  "type": "assistant",
  "message": {
    "content": [
      {
        "thinking": "Claude's thinking process...",
        "signature": "..."
      },
      {
        "type": "text",
        "text": "Response text..."
      },
      {
        "type": "tool_use",
        "id": "toolu_...",
        "name": "ToolName",
        "input": { ... }
      }
    ]
  }
}
```

---

## API Endpoint Summary

| Endpoint | Method | Auth | Status |
|----------|--------|------|--------|
| `api.anthropic.com/v1/sessions/{id}` | GET | Session Token | ✓ Works |
| `api.anthropic.com/v1/sessions/{id}/events` | GET | Session Token | ✓ Works |
| `api.anthropic.com/v1/sessions` | POST | Session Token | ✗ 401 |
| `api.anthropic.com/v1/sessions` | GET | Session Token | ✗ 401 |
| `api.anthropic.com/v1/environments` | GET | Requires x-org-uuid | ✗ 401 |
| `claude.ai/v1/sessions` | POST | Browser Cookies | Cloudflare Protected |

---

## Spawning New Agents: What Would Be Needed

To programmatically spawn new Claude Code Web agents, you would need:

1. **Browser Session Authentication**
   - Valid `sessionKey` cookie from claude.ai
   - This is only available in browser context

2. **Cloudflare Bypass**
   - The `claude.ai/v1/sessions` endpoint is protected by Cloudflare
   - Requires JavaScript execution (not possible from CLI)

3. **Alternative: Claude Agent SDK**
   - For programmatic agent spawning, use the official [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
   - This provides proper API access for creating agents

### Potential Workarounds

1. **Browser Extension**: Create a browser extension that captures the session cookies and allows CLI interaction

2. **Headless Browser**: Use Puppeteer/Playwright to automate browser-based session creation

3. **Official SDK**: Wait for Anthropic to expose session creation in the public API

---

*Document generated: 2026-01-22*
*Based on reverse engineering of Claude Code Web at claude.ai/code*
