import { defineConfig } from "@hey-api/openapi-ts"

export default defineConfig({
  client: "@hey-api/client-fetch",
  input: "../openapi.json",
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
