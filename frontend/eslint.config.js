import js from "@eslint/js"
import globals from "globals"
import reactHooks from "eslint-plugin-react-hooks"
import reactRefresh from "eslint-plugin-react-refresh"
import jsxA11y from "eslint-plugin-jsx-a11y"
import tseslint from "typescript-eslint"

export default tseslint.config(
  { ignores: ["dist", "src/routeTree.gen.ts"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2024,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/no-explicit-any": "warn",
      // autofocus is applied intentionally on primary inputs (login, search,
      // forms) where first-field focus is the expected UX. Treat as advisory.
      "jsx-a11y/no-autofocus": "off",
      // setState-in-effect is noisy for the navigate-on-invalid-token
      // pattern used by verify-email / oauth-callback. The eager state
      // update is correct; downgrade from recommended error to warn.
      "react-hooks/set-state-in-effect": "warn",
      // Purity rule (react-hooks v5) flags legit conditional expressions
      // like `flag && fn()` during render. Downgrade to warn.
      "react-hooks/purity": "warn",
      // Shadcn Label is an htmlFor-forwarding primitive; the associated
      // control is registered via Radix context rather than nesting. The
      // rule can't see that, so it produces false positives across every
      // form in the codebase.
      "jsx-a11y/label-has-associated-control": "off",
      // <h1/h2/h3> with dynamic children are common in card headers.
      "jsx-a11y/heading-has-content": "warn",
      // Pagination / tree-view render anchors with icon-only children.
      "jsx-a11y/anchor-has-content": "warn",
      // Audio preview components use <audio> without captions by design.
      "jsx-a11y/media-has-caption": "warn",
      // Tree-view / approvals banner wrap interactive behavior on divs
      // with ARIA treeitem role; the custom keyboard handling is covered
      // by component-level keyDown logic.
      "jsx-a11y/click-events-have-key-events": "warn",
      "jsx-a11y/no-static-element-interactions": "warn",
      "jsx-a11y/role-has-required-aria-props": "warn",
      "jsx-a11y/role-supports-aria-props": "warn",
    },
  },
)
