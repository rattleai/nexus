import { defineConfig } from "@hey-api/openapi-ts"
import path from "node:path"

export default defineConfig({
  client: "@hey-api/client-fetch",
  // Resolve path relative to this config file so it works regardless of cwd
  input: path.resolve(__dirname, "../openapi.json"),
  output: {
    lint: "eslint",
    path: "src/generated/api",
  },
  plugins: [
    "@hey-api/typescript",
    "@hey-api/sdk",
    {
      name: "@hey-api/schemas",
      type: "json",
    },
  ],
})
