# Plugin Distribution Guide

This directory contains manifests and configuration for distributing the NEXUS platform as a native plugin across AI providers.

## Architecture

```
                    ┌─────────────────────────┐
                    │   NEXUS MCP Server    │
                    │  (Streamable HTTP/stdio) │
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │            │           │           │             │
   Claude Desktop  OpenAI    Langdock   MS Copilot   Gemini CLI
   Claude Code     Responses            (v2.4)
   Cursor          API
   Windsurf
   Cline
```

**MCP is the convergence point.** A single MCP server implementation covers the majority of providers.

## Provider Setup

### Claude Desktop / Claude Code / Cursor
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "nxs": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "NXS_API_KEY", "ghcr.io/${{ github.repository_owner }}/nxs-mcp:latest"]
    }
  }
}
```

### OpenAI (Responses API)
MCP servers are consumed natively:
```json
{
  "tools": [{
    "type": "mcp",
    "server_label": "nxs",
    "server_url": "https://mcp.example.com/mcp",
    "headers": { "Authorization": "Bearer YOUR_API_KEY" }
  }]
}
```

### OpenAI (GPT Actions)
1. Create a Custom GPT in ChatGPT
2. Add Action → Import from URL: `https://api.example.com/.well-known/ai-plugin.json`
3. Configure authentication (Bearer token with your API key)

### Langdock
1. Go to Integrations → Add Integration → MCP Server
2. Enter URL: `https://mcp.example.com/mcp`
3. Select authentication: API Key
4. Enter your NEXUS API key

### Microsoft 365 Copilot
Uses the API plugin manifest at `/.well-known/ai-plugin.json` or the MCP server directly via manifest v2.4:
```json
{
  "runtime": {
    "type": "RemoteMCPServer",
    "spec": { "url": "https://mcp.example.com/mcp" }
  }
}
```

### Gemini CLI
Install the extension from the GitHub repo:
```bash
gemini extensions install https://github.com/rattleai/nxs
```
Or manually copy `gemini-extension.json` to your extensions directory.

### GitHub Copilot
Register as a GitHub App with the skillset defined in `copilot-skillset/skillset.json`.

## Files

| File | Purpose | Consumed By |
|------|---------|-------------|
| `server.json` | MCP Registry manifest | Official MCP Registry, Smithery, mcp.so |
| `gemini-extension.json` | Gemini CLI extension | Gemini CLI |
| `copilot-skillset/skillset.json` | GitHub Copilot skills | GitHub Copilot Extensions |
| `Dockerfile.mcp` | Docker image for MCP server | Claude Desktop, Cursor, Docker-based clients |
| `/.well-known/ai-plugin.json` | Plugin discovery (served by API) | OpenAI GPT Actions, Microsoft Copilot |
| `/.well-known/mcp` | MCP discovery (served by API) | All MCP clients |

## Authentication

All integrations use one of:
- **API Key**: Header `X-API-Key` or `Authorization: Bearer <key>`
- **OAuth 2.1 + PKCE**: For MCP Streamable HTTP transport (production)

Get API keys at: `https://example.com/settings/api-keys`
